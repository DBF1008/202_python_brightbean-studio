"""Tests for configurable approval SLA settings in the reminder pipeline.

Verifies that ``apps.approvals.tasks`` reads every threshold from the
settings cascade (workspace -> org -> app default) instead of using
hardcoded constants, and that the ``email_subject_template`` and
``stalled_post_escalation`` flags drive notification copy and escalation
behaviour respectively.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import ApprovalReminder
from apps.approvals.tasks import (
    _format_subject,
    _get_workspace_config,
    check_approval_reminders,
)
from apps.composer.models import PlatformPost, Post
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.notifications.models import Notification
from apps.organizations.models import Organization
from apps.settings_manager.models import OrgSetting, WorkspaceSetting
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(email, name=""):
    """Create a user, then tear down the auto-provisioned org/workspace.

    The accounts ``post_save`` signal creates a default org + workspace for
    every new user.  Tests that attach the user to a specific org need to
    start from a clean slate so the RBAC middleware (which picks the first
    ``OrgMembership``) doesn't grab the auto-provisioned one.
    """
    user = User.objects.create_user(
        email=email,
        password="testpass123",
        name=name,
        tos_accepted_at=timezone.now(),
    )
    auto_org_ids = list(
        OrgMembership.objects.filter(user=user).values_list("organization_id", flat=True)
    )
    WorkspaceMembership.objects.filter(user=user).delete()
    OrgMembership.objects.filter(user=user).delete()
    Organization.objects.filter(id__in=auto_org_ids).delete()
    return user


def _make_social_account(workspace, platform="facebook", pid=None):
    return SocialAccount.objects.create(
        workspace=workspace,
        platform=platform,
        account_platform_id=pid or f"test-{platform}-id",
        account_name=f"Test {platform}",
    )


def _make_stalled_post(workspace, author, social_account, status, hours_ago):
    """Create a Post + PlatformPost in *status*, updated *hours_ago* hours ago."""
    post = Post.objects.create(
        workspace=workspace,
        author=author,
        caption=f"Stalled post in {workspace.name}",
    )
    pp = PlatformPost.objects.create(
        post=post,
        social_account=social_account,
        status=status,
    )
    # Force updated_at into the past so the threshold logic picks it up.
    Post.objects.filter(id=post.id).update(
        updated_at=timezone.now() - timedelta(hours=hours_ago)
    )
    post.refresh_from_db()
    return post


# ---------------------------------------------------------------------------
# _get_workspace_config tests
# ---------------------------------------------------------------------------

class GetWorkspaceConfigTests(TestCase):
    """Verify the config helper reads the settings cascade correctly."""

    def setUp(self):
        self.org = Organization.objects.create(name="Config Org")
        self.ws = Workspace.objects.create(organization=self.org, name="Config WS")

    def test_app_defaults_when_no_overrides(self):
        cfg = _get_workspace_config(self.ws.id, workspace_org_id=self.org.id)
        self.assertEqual(cfg["internal_reminder_hours"], 24)
        self.assertEqual(cfg["client_reminder_hours"], 48)
        self.assertEqual(cfg["max_reminders"], 2)
        self.assertTrue(cfg["escalation_enabled"])
        self.assertIn("{workspace_name}", cfg["subject_template"])

    def test_org_override(self):
        OrgSetting.objects.create(
            organization=self.org,
            key="approval.internal_reminder_hours",
            value=12,
        )
        OrgSetting.objects.create(
            organization=self.org,
            key="approval.max_reminders_per_post",
            value=5,
        )
        cfg = _get_workspace_config(self.ws.id, workspace_org_id=self.org.id)
        self.assertEqual(cfg["internal_reminder_hours"], 12)
        self.assertEqual(cfg["max_reminders"], 5)
        # Non-overridden values still fall through to app default.
        self.assertEqual(cfg["client_reminder_hours"], 48)

    def test_workspace_override_takes_precedence(self):
        OrgSetting.objects.create(
            organization=self.org,
            key="approval.client_reminder_hours",
            value=72,
        )
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.client_reminder_hours",
            value=6,
        )
        cfg = _get_workspace_config(self.ws.id, workspace_org_id=self.org.id)
        # Workspace wins over org.
        self.assertEqual(cfg["client_reminder_hours"], 6)

    def test_escalation_can_be_disabled_at_org(self):
        OrgSetting.objects.create(
            organization=self.org,
            key="approval.stalled_post_escalation",
            value=False,
        )
        cfg = _get_workspace_config(self.ws.id, workspace_org_id=self.org.id)
        self.assertFalse(cfg["escalation_enabled"])


# ---------------------------------------------------------------------------
# _format_subject tests
# ---------------------------------------------------------------------------

class FormatSubjectTests(TestCase):
    def test_basic_template(self):
        result = _format_subject("{workspace_name} - Posts ready", "My WS")
        self.assertEqual(result, "My WS - Posts ready")

    def test_default_template_from_app_defaults(self):
        tpl = "{workspace_name} - Posts ready for your review"
        result = _format_subject(tpl, "Acme")
        self.assertEqual(result, "Acme - Posts ready for your review")

    def test_bad_template_falls_back(self):
        result = _format_subject("{unknown_placeholder}", "WS")
        # Should not crash; falls back to default message.
        self.assertIn("WS", result)


# ---------------------------------------------------------------------------
# End-to-end reminder pipeline tests
# ---------------------------------------------------------------------------

class ApprovalReminderPipelineTests(TestCase):
    """End-to-end tests for check_approval_reminders with per-workspace config."""

    def setUp(self):
        self.org = Organization.objects.create(name="Pipeline Org")
        self.ws = Workspace.objects.create(organization=self.org, name="Pipeline WS")

        self.reviewer = _make_user("reviewer@example.com", name="Reviewer")
        self.author = _make_user("author@example.com", name="Author")
        self.manager = _make_user("manager@example.com", name="Manager")
        self.client_user = _make_user("client@example.com", name="Client")

        OrgMembership.objects.create(user=self.reviewer, organization=self.org, org_role="member")
        OrgMembership.objects.create(user=self.author, organization=self.org, org_role="member")
        OrgMembership.objects.create(user=self.manager, organization=self.org, org_role="owner")
        OrgMembership.objects.create(user=self.client_user, organization=self.org, org_role="member")

        # Reviewer has approve_posts via custom_role
        from apps.members.models import CustomRole
        self.approver_role = CustomRole.objects.create(
            organization=self.org,
            name="Approver",
            permissions={"approve_posts": True},
        )
        WorkspaceMembership.objects.create(
            user=self.reviewer, workspace=self.ws, workspace_role="editor", custom_role=self.approver_role,
        )
        WorkspaceMembership.objects.create(
            user=self.author, workspace=self.ws, workspace_role="contributor",
        )
        WorkspaceMembership.objects.create(
            user=self.manager, workspace=self.ws, workspace_role="manager",
        )
        WorkspaceMembership.objects.create(
            user=self.client_user, workspace=self.ws, workspace_role="client",
        )

        self.sa = _make_social_account(self.ws)

    def test_default_settings_send_reminder_after_24h(self):
        """With no overrides, a post stalled >24h in pending_review triggers a reminder."""
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        Notification.objects.all().delete()

        check_approval_reminders()

        # Reviewer should get a reminder notification
        reminder_notifs = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        )
        self.assertEqual(reminder_notifs.count(), 1)

        # The reminder record should show count=1
        reminder = ApprovalReminder.objects.get(post=post, stage="pending_review")
        self.assertEqual(reminder.reminder_count, 1)

    def test_workspace_override_shortens_threshold(self):
        """A workspace override of internal_reminder_hours=2 makes a 3h-old post stalled."""
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.internal_reminder_hours",
            value=2,
        )
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=3)
        Notification.objects.all().delete()

        check_approval_reminders()

        reminder_notifs = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        )
        self.assertEqual(reminder_notifs.count(), 1)

    def test_workspace_override_lengthens_threshold_suppresses_reminder(self):
        """A workspace override of internal_reminder_hours=72 means a 25h-old post is NOT stalled."""
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.internal_reminder_hours",
            value=72,
        )
        _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        Notification.objects.all().delete()

        check_approval_reminders()

        reminder_notifs = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        )
        self.assertEqual(reminder_notifs.count(), 0)

    def test_org_override_client_reminder_hours(self):
        """Org override of client_reminder_hours applies to pending_client posts."""
        OrgSetting.objects.create(
            organization=self.org,
            key="approval.client_reminder_hours",
            value=4,
        )
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_client", hours_ago=5)
        Notification.objects.all().delete()

        check_approval_reminders()

        client_notifs = Notification.objects.filter(
            user=self.client_user, event_type="approval_reminder"
        )
        self.assertEqual(client_notifs.count(), 1)

    def test_max_reminders_per_post_respected(self):
        """Once max_reminders is reached, no further reminders are sent."""
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.max_reminders_per_post",
            value=1,
        )
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)

        # Pre-set reminder_count to 1 (= max), so no new reminder should fire.
        ApprovalReminder.objects.create(
            post=post, stage="pending_review", reminder_count=1, escalated=False,
        )
        Notification.objects.all().delete()

        check_approval_reminders()

        reminder_notifs = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        )
        self.assertEqual(reminder_notifs.count(), 0)

    def test_escalation_fires_after_max_reminders(self):
        """After max_reminders, an escalation notification is sent to managers."""
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        # Simulate that 2 reminders have already been sent (default max).
        ApprovalReminder.objects.create(
            post=post, stage="pending_review", reminder_count=2, escalated=False,
        )
        Notification.objects.all().delete()

        check_approval_reminders()

        escalation_notifs = Notification.objects.filter(
            user=self.manager, event_type="approval_stalled"
        )
        self.assertEqual(escalation_notifs.count(), 1)
        self.assertIn("[Escalation]", escalation_notifs.first().title)

        # Reminder should be marked escalated.
        reminder = ApprovalReminder.objects.get(post=post, stage="pending_review")
        self.assertTrue(reminder.escalated)

    def test_escalation_disabled_by_setting(self):
        """When stalled_post_escalation is False, no escalation notification is sent."""
        OrgSetting.objects.create(
            organization=self.org,
            key="approval.stalled_post_escalation",
            value=False,
        )
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        ApprovalReminder.objects.create(
            post=post, stage="pending_review", reminder_count=2, escalated=False,
        )
        Notification.objects.all().delete()

        check_approval_reminders()

        escalation_notifs = Notification.objects.filter(
            user=self.manager, event_type="approval_stalled"
        )
        self.assertEqual(escalation_notifs.count(), 0)

        # But the reminder is still marked escalated (so we don't keep checking).
        reminder = ApprovalReminder.objects.get(post=post, stage="pending_review")
        self.assertTrue(reminder.escalated)

    def test_email_subject_template_applied_to_reminder(self):
        """A custom email_subject_template is used as the notification title."""
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.email_subject_template",
            value="ACTION REQUIRED: {workspace_name} approval queue",
        )
        _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        Notification.objects.all().delete()

        check_approval_reminders()

        notif = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, "ACTION REQUIRED: Pipeline WS approval queue")

    def test_email_subject_template_applied_to_escalation(self):
        """Escalation notification title uses the template with [Escalation] prefix."""
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.email_subject_template",
            value="{workspace_name} review needed",
        )
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        ApprovalReminder.objects.create(
            post=post, stage="pending_review", reminder_count=2, escalated=False,
        )
        Notification.objects.all().delete()

        check_approval_reminders()

        notif = Notification.objects.filter(
            user=self.manager, event_type="approval_stalled"
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.title, "[Escalation] Pipeline WS review needed")

    def test_no_reminder_when_post_not_stalled(self):
        """A post updated recently (within threshold) should not trigger a reminder."""
        _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=1)
        Notification.objects.all().delete()

        check_approval_reminders()

        reminder_notifs = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        )
        self.assertEqual(reminder_notifs.count(), 0)

    def test_cooldown_prevents_duplicate_reminder(self):
        """A reminder sent recently should not be re-sent within the cooldown window."""
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=48)
        # Simulate a reminder sent 1 hour ago (well within the 24h cooldown).
        ApprovalReminder.objects.create(
            post=post,
            stage="pending_review",
            reminder_count=1,
            last_reminder_at=timezone.now() - timedelta(hours=1),
        )
        Notification.objects.all().delete()

        check_approval_reminders()

        reminder_notifs = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        )
        self.assertEqual(reminder_notifs.count(), 0)

    def test_two_workspaces_use_different_settings(self):
        """Two workspaces in the same org can have different SLA thresholds."""
        ws2 = Workspace.objects.create(organization=self.org, name="WS2")
        sa2 = _make_social_account(ws2, platform="instagram", pid="ig-test-id")

        reviewer2 = _make_user("reviewer2@example.com", name="Reviewer2")
        OrgMembership.objects.create(user=reviewer2, organization=self.org, org_role="member")
        from apps.members.models import CustomRole
        role2 = CustomRole.objects.create(
            organization=self.org, name="Approver2", permissions={"approve_posts": True}
        )
        WorkspaceMembership.objects.create(
            user=reviewer2, workspace=ws2, workspace_role="editor", custom_role=role2,
        )

        # WS1: default 24h threshold  -> 25h post IS stalled
        # WS2: override 48h threshold -> 25h post is NOT stalled
        WorkspaceSetting.objects.create(
            workspace=ws2,
            key="approval.internal_reminder_hours",
            value=48,
        )

        _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        _make_stalled_post(ws2, self.author, sa2, "pending_review", hours_ago=25)
        Notification.objects.all().delete()

        check_approval_reminders()

        # WS1 reviewer gets a reminder.
        ws1_notifs = Notification.objects.filter(
            user=self.reviewer, event_type="approval_reminder"
        )
        self.assertEqual(ws1_notifs.count(), 1)

        # WS2 reviewer does NOT get a reminder (25h < 48h threshold).
        ws2_notifs = Notification.objects.filter(
            user=reviewer2, event_type="approval_reminder"
        )
        self.assertEqual(ws2_notifs.count(), 0)

    def test_client_stage_uses_client_reminder_hours(self):
        """Verify pending_client stage uses client_reminder_hours, not internal."""
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.internal_reminder_hours",
            value=1,  # very short — would trigger if wrongly used for client stage
        )
        WorkspaceSetting.objects.create(
            workspace=self.ws,
            key="approval.client_reminder_hours",
            value=100,  # very long — should suppress reminder
        )
        _make_stalled_post(self.ws, self.author, self.sa, "pending_client", hours_ago=5)
        Notification.objects.all().delete()

        check_approval_reminders()

        client_notifs = Notification.objects.filter(
            user=self.client_user, event_type="approval_reminder"
        )
        self.assertEqual(client_notifs.count(), 0)

    def test_already_escalated_not_re_escalated(self):
        """A post already marked escalated should not generate a second escalation."""
        post = _make_stalled_post(self.ws, self.author, self.sa, "pending_review", hours_ago=25)
        ApprovalReminder.objects.create(
            post=post, stage="pending_review", reminder_count=2, escalated=True,
        )
        Notification.objects.all().delete()

        check_approval_reminders()

        escalation_notifs = Notification.objects.filter(
            user=self.manager, event_type="approval_stalled"
        )
        self.assertEqual(escalation_notifs.count(), 0)
