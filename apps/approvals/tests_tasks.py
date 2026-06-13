"""Tests for the settings-driven approval reminder tasks.

These exercise the full reminder link end-to-end (cadence, reminder cap,
escalation, and subject template) and prove the values flow from the settings
cascade: workspace override -> org override -> application default.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.approvals.models import ApprovalReminder
from apps.approvals.tasks import _render_subject, check_approval_reminders
from apps.composer.models import PlatformPost, Post
from apps.members.models import WorkspaceMembership
from apps.notifications.models import EventType, Notification
from apps.organizations.models import Organization
from apps.settings_manager.models import OrgSetting, WorkspaceSetting
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


def _make_user(email):
    return User.objects.create_user(email=email, password="x", tos_accepted_at=timezone.now())


def _stale_post(workspace, status, age_hours):
    """Create a Post + PlatformPost in ``status``, aged ``age_hours`` into the past."""
    post = Post.objects.create(workspace=workspace, caption="needs review")
    account = SocialAccount.objects.create(
        workspace=workspace,
        platform="facebook",
        account_platform_id=f"pid-{post.id}",
        account_name="Page",
        account_handle="page",
        oauth_access_token="tok",
        oauth_refresh_token="ref",
    )
    PlatformPost.objects.create(post=post, social_account=account, status=status)
    # updated_at is auto_now, so backdate it directly to simulate a stalled post.
    Post.objects.filter(id=post.id).update(updated_at=timezone.now() - timedelta(hours=age_hours))
    return post


@pytest.fixture
def org_ws(db):
    org = Organization.objects.create(name="Acme")
    ws = Workspace.objects.create(organization=org, name="Acme")
    return org, ws


@pytest.mark.django_db
def test_internal_reminder_uses_workspace_override(org_ws):
    """A workspace override shortens the internal reminder threshold."""
    _, ws = org_ws
    reviewer = _make_user("rev@example.com")
    WorkspaceMembership.objects.create(user=reviewer, workspace=ws, workspace_role="manager")
    WorkspaceSetting.objects.create(workspace=ws, key="approval.internal_reminder_hours", value=1)

    _stale_post(ws, "pending_review", age_hours=2)  # 2h old, 1h threshold -> fires
    check_approval_reminders()

    notes = Notification.objects.filter(user=reviewer, event_type=EventType.APPROVAL_REMINDER)
    assert notes.count() == 1
    # The configurable subject template becomes the notification title.
    assert notes.first().title == "Acme - Posts ready for your review"


@pytest.mark.django_db
def test_no_reminder_before_threshold(org_ws):
    """With the default 24h threshold, a 2h-old post triggers nothing."""
    _, ws = org_ws
    reviewer = _make_user("rev@example.com")
    WorkspaceMembership.objects.create(user=reviewer, workspace=ws, workspace_role="manager")

    _stale_post(ws, "pending_review", age_hours=2)
    check_approval_reminders()

    assert Notification.objects.filter(event_type=EventType.APPROVAL_REMINDER).count() == 0


@pytest.mark.django_db
def test_escalation_after_max_reminders_override(org_ws):
    """max_reminders_per_post drives when escalation happens."""
    _, ws = org_ws
    reviewer = _make_user("rev@example.com")  # manager -> can approve AND receives escalation
    WorkspaceMembership.objects.create(user=reviewer, workspace=ws, workspace_role="manager")
    WorkspaceSetting.objects.create(workspace=ws, key="approval.internal_reminder_hours", value=1)
    WorkspaceSetting.objects.create(workspace=ws, key="approval.max_reminders_per_post", value=1)

    post = _stale_post(ws, "pending_review", age_hours=2)

    check_approval_reminders()  # reminder #1
    reminder = ApprovalReminder.objects.get(post=post, stage="pending_review")
    assert reminder.reminder_count == 1
    assert reminder.escalated is False

    check_approval_reminders()  # cap (1) reached -> escalate
    reminder.refresh_from_db()
    assert reminder.escalated is True
    assert Notification.objects.filter(user=reviewer, event_type=EventType.APPROVAL_STALLED).count() == 1


@pytest.mark.django_db
def test_escalation_disabled_suppresses_escalation(org_ws):
    """stalled_post_escalation=False stops escalation after the cap."""
    _, ws = org_ws
    reviewer = _make_user("rev@example.com")
    WorkspaceMembership.objects.create(user=reviewer, workspace=ws, workspace_role="manager")
    WorkspaceSetting.objects.create(workspace=ws, key="approval.internal_reminder_hours", value=1)
    WorkspaceSetting.objects.create(workspace=ws, key="approval.max_reminders_per_post", value=1)
    WorkspaceSetting.objects.create(workspace=ws, key="approval.stalled_post_escalation", value=False)

    post = _stale_post(ws, "pending_review", age_hours=2)

    check_approval_reminders()  # reminder #1
    check_approval_reminders()  # cap reached, but escalation disabled

    reminder = ApprovalReminder.objects.get(post=post, stage="pending_review")
    assert reminder.escalated is False
    assert Notification.objects.filter(event_type=EventType.APPROVAL_STALLED).count() == 0


@pytest.mark.django_db
def test_client_reminder_uses_org_override_and_subject_template(org_ws):
    """Org-level overrides apply when there is no workspace override (cascade)."""
    org, ws = org_ws
    client = _make_user("client@example.com")
    WorkspaceMembership.objects.create(user=client, workspace=ws, workspace_role="client")

    OrgSetting.objects.create(organization=org, key="approval.client_reminder_hours", value=1)
    OrgSetting.objects.create(
        organization=org,
        key="approval.email_subject_template",
        value="[{workspace_name}] approval needed",
    )

    _stale_post(ws, "pending_client", age_hours=2)
    check_approval_reminders()

    notes = Notification.objects.filter(user=client, event_type=EventType.APPROVAL_REMINDER)
    assert notes.count() == 1
    assert notes.first().title == "[Acme] approval needed"


def test_render_subject_handles_template_and_fallback():
    """The subject renderer fills {workspace_name} and falls back when invalid."""

    class _WS:
        name = "Acme"

    ws = _WS()
    assert _render_subject("Hi {workspace_name}", ws) == "Hi Acme"
    # Unknown placeholder -> safe default.
    assert _render_subject("{nope}", ws) == "Acme - Posts ready for your review"
    # Empty/None -> safe default.
    assert _render_subject("", ws) == "Acme - Posts ready for your review"
    assert _render_subject(None, ws) == "Acme - Posts ready for your review"
