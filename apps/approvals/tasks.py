"""Background tasks for approval workflow reminders.

All reminder thresholds, escalation behaviour and notification copy are
driven by the settings cascade (workspace -> org -> app default) defined
in ``apps.settings_manager``.  The relevant setting keys are:

* ``approval.internal_reminder_hours``  - hours before an internal-review
  reminder is sent (and the cooldown between successive reminders).
* ``approval.client_reminder_hours``    - same, for client approval stage.
* ``approval.max_reminders_per_post``   - after this many reminders the
  post is considered stalled and (optionally) escalated.
* ``approval.stalled_post_escalation``  - boolean; when *False* the
  escalation notification is suppressed.
* ``approval.email_subject_template``   - a format string with
  ``{workspace_name}`` placeholder used as the notification title for
  reminder and escalation notifications.

The :func:`check_approval_reminders` entry-point is safe to call every
hour from cron / ``process_tasks`` / the ``run_approval_reminders``
management command.
"""

import logging
from datetime import timedelta

from django.utils import timezone

from apps.composer.models import Post
from apps.members.models import WorkspaceMembership
from apps.notifications.engine import notify
from apps.notifications.models import EventType
from apps.settings_manager.helpers import get_setting

from .models import ApprovalReminder

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-workspace config
# ---------------------------------------------------------------------------

def _get_workspace_config(workspace_id, workspace_org_id=None):
    """Return a dict of approval SLA settings for *workspace_id*.

    Values follow the settings cascade: workspace override -> org override
    -> application default.  The result is a plain dict so callers never
    need to import ``settings_manager`` themselves.
    """
    g = lambda key: get_setting(workspace_id, key, workspace_org_id=workspace_org_id)  # noqa: E731
    return {
        "internal_reminder_hours": int(g("approval.internal_reminder_hours")),
        "client_reminder_hours": int(g("approval.client_reminder_hours")),
        "max_reminders": int(g("approval.max_reminders_per_post")),
        "escalation_enabled": bool(g("approval.stalled_post_escalation")),
        "subject_template": str(g("approval.email_subject_template")),
    }


def _format_subject(template, workspace_name, **extra):
    """Render *template* with ``{workspace_name}`` and any *extra* kwargs.

    Unknown placeholders are silently ignored so a misconfigured template
    never crashes the reminder loop.
    """
    try:
        return template.format(workspace_name=workspace_name, **extra)
    except (KeyError, IndexError, ValueError):
        # Fallback: at least include the workspace name.
        return f"{workspace_name} - Posts ready for your review"


# ---------------------------------------------------------------------------
# Main entry-point
# ---------------------------------------------------------------------------

def check_approval_reminders():
    """Check for stalled approvals and send reminders.

    Should be run periodically (every hour).  Each workspace's posts are
    evaluated against that workspace's own SLA settings.
    """
    now = timezone.now()

    # Collect workspace IDs that have posts in either approval stage so we
    # can look up per-workspace config exactly once per workspace.
    workspace_ids = list(
        Post.objects.filter(
            platform_posts__status__in=["pending_review", "pending_client"],
        )
        .values_list("workspace_id", flat=True)
        .distinct()
    )

    # Pre-fetch org IDs so _get_workspace_config can skip an extra query.
    from apps.workspaces.models import Workspace

    ws_org_map = dict(
        Workspace.objects.filter(id__in=workspace_ids).values_list("id", "organization_id")
    )

    for ws_id in workspace_ids:
        org_id = ws_org_map.get(ws_id)
        try:
            config = _get_workspace_config(ws_id, workspace_org_id=org_id)
        except Exception:
            logger.exception("Failed to load approval config for workspace %s", ws_id)
            continue

        # 1. Posts stuck in pending_review
        _process_stage(
            workspace_id=ws_id,
            stage="pending_review",
            status="pending_review",
            threshold_hours=config["internal_reminder_hours"],
            max_reminders=config["max_reminders"],
            escalation_enabled=config["escalation_enabled"],
            subject_template=config["subject_template"],
            now=now,
        )

        # 2. Posts stuck in pending_client
        _process_stage(
            workspace_id=ws_id,
            stage="pending_client",
            status="pending_client",
            threshold_hours=config["client_reminder_hours"],
            max_reminders=config["max_reminders"],
            escalation_enabled=config["escalation_enabled"],
            subject_template=config["subject_template"],
            now=now,
        )


# ---------------------------------------------------------------------------
# Per-stage processing
# ---------------------------------------------------------------------------

def _process_stage(
    *,
    workspace_id,
    stage,
    status,
    threshold_hours,
    max_reminders,
    escalation_enabled,
    subject_template,
    now,
):
    """Process reminders for a specific approval stage within one workspace."""
    threshold = now - timedelta(hours=threshold_hours)

    stalled_posts = (
        Post.objects.filter(
            workspace_id=workspace_id,
            platform_posts__status=status,
            updated_at__lte=threshold,
        )
        .distinct()
        .select_related("workspace", "author")
    )

    for post in stalled_posts:
        reminder, created = ApprovalReminder.objects.get_or_create(
            post=post,
            stage=stage,
            defaults={"reminder_count": 0},
        )

        # Check if we should send a reminder
        if reminder.reminder_count >= max_reminders:
            # Already sent max reminders - escalate if not already done and
            # escalation is enabled for this workspace.
            if not reminder.escalated:
                if escalation_enabled:
                    _escalate(post, stage, subject_template)
                reminder.escalated = True
                reminder.save(update_fields=["escalated"])
            continue

        # Check cooldown (don't spam - wait at least threshold_hours between reminders)
        if reminder.last_reminder_at:
            cooldown = reminder.last_reminder_at + timedelta(hours=threshold_hours)
            if now < cooldown:
                continue

        # Send reminder
        if stage == "pending_review":
            _remind_reviewers(post, subject_template)
        elif stage == "pending_client":
            _remind_clients(post, subject_template)

        reminder.reminder_count += 1
        reminder.last_reminder_at = now
        reminder.save(update_fields=["reminder_count", "last_reminder_at"])

        logger.info(
            "Sent reminder #%d for post %s (stage: %s, workspace: %s)",
            reminder.reminder_count,
            post.id,
            stage,
            workspace_id,
        )


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

def _remind_reviewers(post, subject_template):
    """Send reminder to workspace members with approve_posts permission."""
    workspace = post.workspace
    subject = _format_subject(subject_template, workspace.name)

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


def _remind_clients(post, subject_template):
    """Send reminder to client members."""
    workspace = post.workspace
    subject = _format_subject(subject_template, workspace.name)

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


def _escalate(post, stage, subject_template):
    """Notify workspace managers that a post is stalled."""
    workspace = post.workspace
    stage_label = "internal review" if stage == "pending_review" else "client approval"

    subject = _format_subject(subject_template, workspace.name)

    manager_memberships = WorkspaceMembership.objects.filter(
        workspace=workspace,
        workspace_role__in=[
            WorkspaceMembership.WorkspaceRole.OWNER,
            WorkspaceMembership.WorkspaceRole.MANAGER,
        ],
    ).select_related("user")

    for membership in manager_memberships:
        notify(
            user=membership.user,
            event_type=EventType.APPROVAL_STALLED,
            title=f"[Escalation] {subject}",
            body=f'A post in {workspace.name} has been stuck in {stage_label} after multiple reminders: "{post.caption_snippet}"',
            data={
                "post_id": str(post.id),
                "workspace_id": str(workspace.id),
                "stage": stage,
            },
        )
