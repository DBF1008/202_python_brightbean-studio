"""SLA re-trigger behaviour for the Unified Social Inbox.

These tests pin down the contract that overdue alerting is *repeatable*: it must
recompute on every worker pass from the message's current cycle and owner, so
reopen, reassignment and config changes all re-fire correctly (and never spam).
"""

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.inbox import sla
from apps.inbox.models import InboxMessage, InboxSLAConfig
from apps.inbox.tasks import InboxSyncEngine
from apps.members.models import WorkspaceMembership
from apps.notifications.models import EventType, Notification
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

Status = InboxMessage.Status


def _make_user(email):
    return User.objects.create_user(
        email=email,
        password="testpass123",
        name=email.split("@")[0],
        tos_accepted_at=timezone.now(),
    )


def _sla_count(user):
    return Notification.objects.filter(user=user, event_type=EventType.INBOX_SLA_OVERDUE).count()


def _run_sla():
    InboxSyncEngine().check_sla()


@pytest.fixture
def workspace(db, organization):
    return Workspace.objects.create(name="Test WS", organization=organization)


@pytest.fixture
def account(db, workspace):
    return SocialAccount.objects.create(
        workspace=workspace,
        platform="facebook",
        account_platform_id="page-1",
        account_name="Test Page",
    )


@pytest.fixture
def config(db, workspace):
    return InboxSLAConfig.objects.create(
        workspace=workspace,
        target_response_minutes=60,
        is_active=True,
        auto_resolve_on_reply=True,
    )


@pytest.fixture
def agent(db):
    return _make_user("agent-a@example.com")


@pytest.fixture
def make_message(workspace, account):
    def _make(*, received_minutes_ago, status=Status.OPEN, assigned_to=None, extra=None):
        return InboxMessage.objects.create(
            workspace=workspace,
            social_account=account,
            platform_message_id=f"m-{uuid.uuid4()}",
            sender_name="Alice",
            body="anyone there?",
            status=status,
            assigned_to=assigned_to,
            received_at=timezone.now() - timedelta(minutes=received_minutes_ago),
            extra=extra if extra is not None else {},
        )

    return _make


def _backdate_anchor(message, minutes_ago):
    """Force the current cycle to have started ``minutes_ago`` for overdue tests."""
    message.extra["sla_started_at"] = (timezone.now() - timedelta(minutes=minutes_ago)).isoformat()
    message.save(update_fields=["extra"])


# --- Worker idempotency -----------------------------------------------------


@pytest.mark.django_db
def test_overdue_notifies_once_and_is_idempotent(config, agent, make_message):
    msg = make_message(received_minutes_ago=90, status=Status.OPEN, assigned_to=agent)

    _run_sla()
    _run_sla()  # second pass must not double-notify within the same cycle

    assert _sla_count(agent) == 1
    msg.refresh_from_db()
    assert msg.extra.get("sla_notified") is True


@pytest.mark.django_db
def test_not_yet_overdue_is_silent(config, agent, make_message):
    make_message(received_minutes_ago=10, status=Status.OPEN, assigned_to=agent)

    _run_sla()

    assert _sla_count(agent) == 0


@pytest.mark.django_db
def test_resolved_message_is_not_tracked(config, agent, make_message):
    make_message(received_minutes_ago=90, status=Status.RESOLVED, assigned_to=agent)

    _run_sla()

    assert _sla_count(agent) == 0


# --- Reopen restarts the clock ----------------------------------------------


@pytest.mark.django_db
def test_reopen_restarts_clock_and_retriggers(config, agent, make_message):
    msg = make_message(received_minutes_ago=90, status=Status.OPEN, assigned_to=agent)

    _run_sla()
    assert _sla_count(agent) == 1

    # Resolve, then reopen via the shared status helper (as the views do).
    sla.transition_status(msg, Status.RESOLVED)
    msg.save()
    sla.transition_status(msg, Status.OPEN)
    msg.save()
    msg.refresh_from_db()

    # The clock restarted at reopen time, so the message is no longer overdue
    # even though it was received 90 minutes ago.
    assert sla.sla_anchor(msg) > msg.received_at
    _run_sla()
    assert _sla_count(agent) == 1

    # Once the fresh window elapses, the overdue alert fires again.
    _backdate_anchor(msg, minutes_ago=90)
    _run_sla()
    assert _sla_count(agent) == 2


# --- Reassignment re-notifies the latest owner ------------------------------


@pytest.mark.django_db
def test_reassign_renotifies_new_owner(config, agent, make_message):
    other = _make_user("agent-b@example.com")
    msg = make_message(received_minutes_ago=90, status=Status.OPEN, assigned_to=agent)

    _run_sla()
    assert _sla_count(agent) == 1
    assert _sla_count(other) == 0

    # Reassign (as assign_message does): reload the row first, like the view's
    # get_object_or_404 would, then clear notified while keeping the clock.
    msg.refresh_from_db()
    msg.assigned_to = other
    changed = sla.on_reassign(msg)
    msg.save()
    assert changed is True

    _run_sla()
    assert _sla_count(other) == 1
    assert _sla_count(agent) == 1  # old owner not pinged again


@pytest.mark.django_db
def test_reassign_does_not_reset_clock(config, agent, make_message):
    other = _make_user("agent-c@example.com")
    msg = make_message(received_minutes_ago=90, status=Status.OPEN, assigned_to=agent)
    _backdate_anchor(msg, minutes_ago=90)
    anchor_before = sla.sla_anchor(msg)

    msg.assigned_to = other
    sla.on_reassign(msg)
    msg.save()
    msg.refresh_from_db()

    assert sla.sla_anchor(msg) == anchor_before


# --- Config changes re-trigger ----------------------------------------------


@pytest.mark.django_db
def test_lengthening_target_clears_then_refires(config, agent, make_message):
    msg = make_message(received_minutes_ago=90, status=Status.OPEN, assigned_to=agent)

    _run_sla()
    assert _sla_count(agent) == 1

    # Admin lengthens the target so the message is no longer overdue.
    config.target_response_minutes = 600
    config.save(update_fields=["target_response_minutes"])

    _run_sla()
    assert _sla_count(agent) == 1
    msg.refresh_from_db()
    assert "sla_notified" not in msg.extra  # re-armed for the new deadline

    # When it crosses the *new* (longer) deadline, it fires again.
    _backdate_anchor(msg, minutes_ago=700)
    _run_sla()
    assert _sla_count(agent) == 2


@pytest.mark.django_db
def test_inactive_config_never_notifies(config, agent, make_message):
    config.is_active = False
    config.save(update_fields=["is_active"])
    make_message(received_minutes_ago=90, status=Status.OPEN, assigned_to=agent)

    _run_sla()

    assert _sla_count(agent) == 0


# --- Reply semantics --------------------------------------------------------


@pytest.mark.django_db
def test_auto_resolve_on_reply_stops_tracking(config, agent, make_message):
    msg = make_message(
        received_minutes_ago=90,
        status=Status.OPEN,
        assigned_to=agent,
        extra={"sla_started_at": (timezone.now() - timedelta(minutes=90)).isoformat()},
    )

    # Mirror send_reply's auto-resolve branch.
    changed = sla.transition_status(msg, Status.RESOLVED)
    msg.save()

    assert changed is True
    assert msg.status == Status.RESOLVED
    assert "sla_started_at" not in msg.extra
    assert "sla_notified" not in msg.extra

    _run_sla()
    assert _sla_count(agent) == 0


@pytest.mark.django_db
def test_reply_without_auto_resolve_keeps_tracking(config, agent, make_message):
    config.auto_resolve_on_reply = False
    config.save(update_fields=["auto_resolve_on_reply"])

    msg = make_message(received_minutes_ago=90, status=Status.UNREAD, assigned_to=agent)
    _backdate_anchor(msg, minutes_ago=90)
    anchor_before = sla.sla_anchor(msg)

    # send_reply only bumps unread -> open here; the cycle must be preserved.
    changed = sla.transition_status(msg, Status.OPEN)
    msg.save()
    msg.refresh_from_db()

    assert changed is False
    assert sla.sla_anchor(msg) == anchor_before

    _run_sla()
    assert _sla_count(agent) == 1


# --- Anchor / backward compatibility ----------------------------------------


@pytest.mark.django_db
def test_anchor_falls_back_to_received_at(make_message):
    msg = make_message(received_minutes_ago=30, status=Status.OPEN, extra={})

    assert sla.sla_anchor(msg) == msg.received_at
    assert msg.sla_anchor == msg.received_at


@pytest.mark.django_db
def test_legacy_message_without_anchor_still_overdue(config, agent, make_message):
    # A row created before cycle tracking: no sla_started_at, only received_at.
    make_message(received_minutes_ago=120, status=Status.OPEN, assigned_to=agent, extra={})

    _run_sla()

    assert _sla_count(agent) == 1


# --- Unassigned fallback ----------------------------------------------------


@pytest.mark.django_db
def test_unassigned_overdue_notifies_owners_and_managers(config, workspace, make_message):
    owner = _make_user("owner@example.com")
    manager = _make_user("manager@example.com")
    viewer = _make_user("viewer@example.com")
    WorkspaceMembership.objects.create(
        user=owner, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.OWNER
    )
    WorkspaceMembership.objects.create(
        user=manager, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.MANAGER
    )
    WorkspaceMembership.objects.create(
        user=viewer, workspace=workspace, workspace_role=WorkspaceMembership.WorkspaceRole.VIEWER
    )

    make_message(received_minutes_ago=90, status=Status.OPEN, assigned_to=None)

    _run_sla()

    assert _sla_count(owner) == 1
    assert _sla_count(manager) == 1
    assert _sla_count(viewer) == 0
