"""Background tasks for approval workflow reminders.

Reminder cadence, the reminder cap, escalation, and the reminder email subject
are all driven by the settings cascade (workspace -> org -> app default),
resolved per workspace via ``apps.settings_manager``. The relevant keys:

    approval.internal_reminder_hours  - cadence/threshold for pending_review
    approval.client_reminder_hours    - cadence/threshold for pending_client
    approval.max_reminders_per_post   - reminders sent before escalation
    approval.stalled_post_escalation  - whether to escalate after the cap
    approval.email_subject_template   - subject/title of reminder notifications
"""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.composer.models import Post
from apps.members.models import WorkspaceMembership
from apps.notifications.engine import notify
from apps.notifications.models import EventType
from apps.settings_manager.defaults import APP_DEFAULTS
from apps.settings_manager.helpers import get_setting

from .models import ApprovalReminder

logger = logging.getLogger(__name__)

# Each approval stage maps to a PlatformPost status (the stage label and the
# status string are identical) and to the settings key that controls how long a
# post sits before a reminder fires (this interval is also the reminder cooldown).
STAGE_REMINDER_HOURS_KEY = {
    "pending_review": "approval.internal_reminder_hours",
    "pending_client": "approval.client_reminder_hours",
}


def check_approval_reminders():
    """Check for stalled approvals and send reminders.

    Should be run periodically (every hour). Thresholds, the reminder cap, and
    escalation are resolved per workspace from the settings cascade, so each
    workspace (or its org) can tune its own approval SLA.
    """
    now = timezone.now()

    for stage, reminder_hours_key in STAGE_REMINDER_HOURS_KEY.items():
        _process_stage(stage=stage, reminder_hours_key=reminder_hours_key, now=now)


def _process_stage(stage, reminder_hours_key, now):
    """Send reminders for a single approval stage, applying per-workspace settings.

    The stage label doubles as the PlatformPost status to match on.
    """
    # Workspaces that currently have at least one post sitting in this status.
    # Settings are resolved once per workspace (not per post).
    workspace_rows = (
        Post.objects.filter(platform_posts__status=stage)
        .values_list("workspace_id", "workspace__organization_id")
        .distinct()
    )

    for workspace_id, org_id in workspace_rows:
        reminder_hours = _get_int_setting(workspace_id, reminder_hours_key, org_id)
        max_reminders = _get_int_setting(workspace_id, "approval.max_reminders_per_post", org_id)
        escalation_enabled = bool(get_setting(workspace_id, "approval.stalled_post_escalation", org_id))
        subject_template = get_setting(workspace_id, "approval.email_subject_template", org_id)

        threshold = now - timedelta(hours=reminder_hours)
        stalled_posts = (
            Post.objects.filter(
                workspace_id=workspace_id,
                platform_posts__status=stage,
                updated_at__lte=threshold,
            )
            .distinct()
            .select_related("workspace", "author")
        )

        for post in stalled_posts:
            _process_post(
                post=post,
                stage=stage,
                now=now,
                reminder_hours=reminder_hours,
                max_reminders=max_reminders,
                escalation_enabled=escalation_enabled,
                subject_template=subject_template,
            )


def _process_post(post, stage, now, reminder_hours, max_reminders, escalation_enabled, subject_template):
    """Apply the reminder/escalation state machine to a single stalled post."""
    reminder, _ = ApprovalReminder.objects.get_or_create(
        post=post,
        stage=stage,
        defaults={"reminder_count": 0},
    )

    # Cap reached: escalate once (if enabled), then stop reminding.
    if reminder.reminder_count >= max_reminders:
        if escalation_enabled and not reminder.escalated:
            _escalate(post, stage)
            reminder.escalated = True
            reminder.save(update_fields=["escalated"])
        return

    # Cooldown: wait at least one reminder interval between reminders.
    if reminder.last_reminder_at:
        cooldown = reminder.last_reminder_at + timedelta(hours=reminder_hours)
        if now < cooldown:
            return

    subject = _render_subject(subject_template, post.workspace)
    if stage == "pending_review":
        _remind_reviewers(post, subject)
    elif stage == "pending_client":
        _remind_clients(post, subject)

    reminder.reminder_count += 1
    reminder.last_reminder_at = now
    reminder.save(update_fields=["reminder_count", "last_reminder_at"])

    logger.info(
        "Sent reminder #%d for post %s (stage: %s)",
        reminder.reminder_count,
        post.id,
        stage,
    )


def _get_int_setting(workspace_id, key, org_id):
    """Resolve an integer setting from the cascade.

    Falls back to the application default if a stored override is non-numeric
    (settings are user-editable, so a bad value must not abort the whole run).
    """
    raw = get_setting(workspace_id, key, org_id)
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning("Non-integer setting %s=%r; using app default", key, raw)
        return int(APP_DEFAULTS[key])


def _render_subject(template, workspace):
    """Render the configurable reminder subject template.

    Supports the ``{workspace_name}`` placeholder. Falls back to the app
    default wording when the template is empty or malformed.
    """
    default = APP_DEFAULTS["approval.email_subject_template"].format(workspace_name=workspace.name)
    if not template:
        return default
    try:
        return template.format(workspace_name=workspace.name)
    except (KeyError, IndexError, ValueError):
        logger.warning("Invalid approval.email_subject_template: %r", template)
        return default


def _remind_reviewers(post, subject):
    """Send reminder to workspace members with approve_posts permission."""
    workspace = post.workspace
    memberships = WorkspaceMembership.objects.filter(
        workspace=workspace,
    ).select_related("user", "custom_role")

    for membership in memberships:
        perms = membership.effective_permissions
        if perms.get("approve_posts", False):
            notify(
                user=membership.user,
                event_type=EventType.APPROVAL_REMINDER,
                title=subject,
                body=f'A post in {workspace.name} has been waiting for review: "{post.caption_snippet}"',
                data={
                    "post_id": str(post.id),
                    "workspace_id": str(workspace.id),
                },
            )


def _remind_clients(post, subject):
    """Send reminder to client members."""
    workspace = post.workspace
    client_memberships = WorkspaceMembership.objects.filter(
        workspace=workspace,
        workspace_role=WorkspaceMembership.WorkspaceRole.CLIENT,
    ).select_related("user")

    for membership in client_memberships:
        notify(
            user=membership.user,
            event_type=EventType.APPROVAL_REMINDER,
            title=subject,
            body=f"Content in {workspace.name} is waiting for your review.",
            data={
                "post_id": str(post.id),
                "workspace_id": str(workspace.id),
            },
        )


def _escalate(post, stage):
    """Notify workspace managers that a post is stalled."""
    workspace = post.workspace
    manager_memberships = WorkspaceMembership.objects.filter(
        workspace=workspace,
        workspace_role__in=[
            WorkspaceMembership.WorkspaceRole.OWNER,
            WorkspaceMembership.WorkspaceRole.MANAGER,
        ],
    ).select_related("user")

    stage_label = "internal review" if stage == "pending_review" else "client approval"

    for membership in manager_memberships:
        notify(
            user=membership.user,
            event_type=EventType.APPROVAL_STALLED,
            title="Stalled post needs attention",
            body=f'A post in {workspace.name} has been stuck in {stage_label} after multiple reminders: "{post.caption_snippet}"',
            data={
                "post_id": str(post.id),
                "workspace_id": str(workspace.id),
                "stage": stage,
            },
        )
