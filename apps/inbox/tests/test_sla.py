"""Tests for repeatable SLA tracking.

Covers:
* Fingerprint-based dedup in ``check_sla()``
* Reopen resets the SLA clock and re-triggers notifications
* Reassignment invalidates SLA state so the new owner is notified
* SLA config changes bump the version and cause re-evaluation
* Auto-resolve on reply clears SLA state
* Bulk actions (resolve / archive / assign) invalidate SLA state
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.inbox.models import InboxMessage, InboxSLAConfig
from apps.inbox.tasks import InboxSyncEngine
from apps.members.models import OrgMembership, WorkspaceMembership
from apps.notifications.models import Notification
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Test Org")


@pytest.fixture
def ws(db, org):
    return Workspace.objects.create(name="Test WS", organization=org)


@pytest.fixture
def agent(db):
    return User.objects.create_user(
        email="agent@example.com", password="testpass123", name="Agent", tos_accepted_at=timezone.now()
    )


@pytest.fixture
def manager_user(db):
    return User.objects.create_user(
        email="mgr@example.com", password="testpass123", name="Manager", tos_accepted_at=timezone.now()
    )


@pytest.fixture
def membership(db, agent, ws):
    OrgMembership.objects.create(user=agent, organization=ws.organization, org_role=OrgMembership.OrgRole.MEMBER)
    return WorkspaceMembership.objects.create(
        user=agent, workspace=ws, workspace_role=WorkspaceMembership.WorkspaceRole.EDITOR
    )


@pytest.fixture
def manager_membership(db, manager_user, ws):
    OrgMembership.objects.create(
        user=manager_user, organization=ws.organization, org_role=OrgMembership.OrgRole.OWNER
    )
    return WorkspaceMembership.objects.create(
        user=manager_user, workspace=ws, workspace_role=WorkspaceMembership.WorkspaceRole.MANAGER
    )


@pytest.fixture
def account(db, ws):
    return SocialAccount.objects.create(
        workspace=ws,
        platform="facebook",
        account_platform_id="page-1",
        account_name="Test Page",
        connection_status=SocialAccount.ConnectionStatus.CONNECTED,
    )


@pytest.fixture
def sla(db, ws):
    return InboxSLAConfig.objects.create(workspace=ws, target_response_minutes=60, is_active=True)


def _make_message(account, ws, *, status="unread", received_offset_minutes=120, assigned_to=None):
    """Create a test InboxMessage that is already overdue by default."""
    return InboxMessage.objects.create(
        workspace=ws,
        social_account=account,
        platform_message_id=f"msg-{InboxMessage.objects.count()}",
        sender_name="Customer",
        body="Hello?",
        status=status,
        received_at=timezone.now() - timedelta(minutes=received_offset_minutes),
        assigned_to=assigned_to,
    )


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------


class TestComputeSlaFingerprint:
    def test_active_unassigned_v1(self):
        fp = InboxMessage.compute_sla_fingerprint("unread", None, 1)
        assert fp == "1:none:1"

    def test_active_assigned_v1(self, agent):
        fp = InboxMessage.compute_sla_fingerprint("open", agent.id, 1)
        assert fp == f"1:{agent.id}:1"

    def test_resolved_is_inactive(self):
        fp = InboxMessage.compute_sla_fingerprint("resolved", None, 1)
        assert fp == "0:none:1"

    def test_config_version_changes_fingerprint(self):
        fp1 = InboxMessage.compute_sla_fingerprint("open", None, 1)
        fp2 = InboxMessage.compute_sla_fingerprint("open", None, 2)
        assert fp1 != fp2


# ---------------------------------------------------------------------------
# check_sla() behaviour
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckSla:
    @patch("apps.inbox.tasks.notify")
    def test_notifies_overdue_and_stores_fingerprint(self, mock_notify, ws, account, sla, manager_membership):
        msg = _make_message(account, ws)
        engine = InboxSyncEngine()
        engine.check_sla()

        msg.refresh_from_db()
        assert "sla_state" in msg.extra
        assert msg.extra["sla_state"]["fp"] == InboxMessage.compute_sla_fingerprint("unread", None, sla.version)
        assert mock_notify.called

    @patch("apps.inbox.tasks.notify")
    def test_same_state_does_not_renotify(self, mock_notify, ws, account, sla, manager_membership):
        _make_message(account, ws)
        engine = InboxSyncEngine()
        engine.check_sla()
        assert mock_notify.call_count >= 1

        mock_notify.reset_mock()
        engine.check_sla()
        assert mock_notify.call_count == 0

    @patch("apps.inbox.tasks.notify")
    def test_legacy_sla_notified_is_migrated(self, mock_notify, ws, account, sla, manager_membership):
        msg = _make_message(account, ws)
        msg.extra["sla_notified"] = True
        msg.save(update_fields=["extra"])

        engine = InboxSyncEngine()
        engine.check_sla()

        msg.refresh_from_db()
        assert "sla_notified" not in msg.extra
        assert "sla_state" in msg.extra
        assert mock_notify.called


# ---------------------------------------------------------------------------
# Reopen
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReopen:
    @patch("apps.inbox.tasks.notify")
    def test_reopen_resets_clock_and_retriggers(self, mock_notify, ws, account, sla, agent, membership):
        msg = _make_message(account, ws, assigned_to=agent)

        engine = InboxSyncEngine()
        engine.check_sla()
        assert mock_notify.call_count == 1

        # Resolve
        msg.status = InboxMessage.Status.RESOLVED
        msg.invalidate_sla_state(save=False)
        msg.save(update_fields=["status", "extra"])

        mock_notify.reset_mock()

        # Reopen — should reset SLA clock
        old_received = msg.received_at
        msg.status = InboxMessage.Status.OPEN
        msg.reset_sla_clock(save=True)

        msg.refresh_from_db()
        assert msg.received_at > old_received
        assert "sla_state" not in msg.extra

        # Make it overdue again (simulate time passing past the new clock)
        msg.received_at = timezone.now() - timedelta(minutes=120)
        msg.save(update_fields=["received_at"])

        engine.check_sla()
        assert mock_notify.call_count == 1


# ---------------------------------------------------------------------------
# Reassign
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReassign:
    @patch("apps.inbox.tasks.notify")
    def test_reassign_triggers_notification_to_new_owner(
        self, mock_notify, ws, account, sla, agent, membership, manager_user, manager_membership
    ):
        msg = _make_message(account, ws, assigned_to=agent)

        engine = InboxSyncEngine()
        engine.check_sla()

        # Notification went to agent
        notified_users = {call.kwargs["user"].id for call in mock_notify.call_args_list}
        assert agent.id in notified_users

        mock_notify.reset_mock()

        # Reassign to manager
        msg.assigned_to = manager_user
        msg.invalidate_sla_state(save=False)
        msg.save(update_fields=["assigned_to", "extra"])

        engine.check_sla()
        notified_users = {call.kwargs["user"].id for call in mock_notify.call_args_list}
        assert manager_user.id in notified_users
        assert agent.id not in notified_users


# ---------------------------------------------------------------------------
# Config change
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConfigChange:
    def test_save_bumps_version_on_target_change(self, sla):
        old_version = sla.version
        sla.target_response_minutes = 30
        sla.save()
        sla.refresh_from_db()
        assert sla.version == old_version + 1

    def test_save_bumps_version_on_toggle(self, sla):
        old_version = sla.version
        sla.is_active = False
        sla.save()
        sla.refresh_from_db()
        assert sla.version == old_version + 1

    def test_save_no_bump_on_auto_resolve_change(self, sla):
        """Changing only auto_resolve_on_reply should NOT bump version
        (it does not affect the SLA timer calculation)."""
        old_version = sla.version
        sla.auto_resolve_on_reply = False
        sla.save()
        sla.refresh_from_db()
        assert sla.version == old_version

    @patch("apps.inbox.tasks.notify")
    def test_config_change_retriggers_overdue(self, mock_notify, ws, account, sla, manager_membership):
        msg = _make_message(account, ws)

        engine = InboxSyncEngine()
        engine.check_sla()
        assert mock_notify.call_count >= 1

        mock_notify.reset_mock()

        # Change config → bumps version → invalidates cached fingerprint
        sla.target_response_minutes = 30
        sla.save()

        # Bulk invalidate (as the sla_config view would do)
        InboxMessage.bulk_invalidate_sla_state(InboxMessage.objects.filter(workspace=ws))

        engine.check_sla()
        assert mock_notify.call_count >= 1


# ---------------------------------------------------------------------------
# Auto-resolve on reply
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestAutoResolve:
    def test_reply_auto_resolve_clears_sla_state(self, ws, account, sla, agent, membership):
        msg = _make_message(account, ws, status="open", assigned_to=agent)
        # Simulate a previous SLA notification
        msg.extra["sla_state"] = {"fp": "old", "notified_at": ""}
        msg.save(update_fields=["extra"])

        # Simulate what send_reply does
        msg.status = InboxMessage.Status.RESOLVED
        msg.invalidate_sla_state(save=False)
        msg.save(update_fields=["status", "extra"])

        msg.refresh_from_db()
        assert msg.status == InboxMessage.Status.RESOLVED
        assert "sla_state" not in msg.extra


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestBulkActions:
    def test_bulk_resolve_invalidates_sla(self, ws, account, sla):
        m1 = _make_message(account, ws)
        m2 = _make_message(account, ws)
        for m in (m1, m2):
            m.extra["sla_state"] = {"fp": "x", "notified_at": ""}
            m.save(update_fields=["extra"])

        qs = InboxMessage.objects.filter(id__in=[m1.id, m2.id])
        count = InboxMessage.bulk_invalidate_sla_state(qs)
        assert count == 2

        m1.refresh_from_db()
        m2.refresh_from_db()
        assert "sla_state" not in m1.extra
        assert "sla_state" not in m2.extra

    def test_bulk_archive_invalidates_sla(self, ws, account, sla):
        msg = _make_message(account, ws)
        msg.extra["sla_state"] = {"fp": "x", "notified_at": ""}
        msg.save(update_fields=["extra"])

        qs = InboxMessage.objects.filter(id=msg.id)
        InboxMessage.bulk_invalidate_sla_state(qs)
        qs.update(status=InboxMessage.Status.ARCHIVED)

        msg.refresh_from_db()
        assert msg.status == InboxMessage.Status.ARCHIVED
        assert "sla_state" not in msg.extra

    def test_bulk_assign_invalidates_sla(self, ws, account, sla, agent, membership):
        msg = _make_message(account, ws)
        msg.extra["sla_state"] = {"fp": "x", "notified_at": ""}
        msg.save(update_fields=["extra"])

        qs = InboxMessage.objects.filter(id=msg.id)
        InboxMessage.bulk_invalidate_sla_state(qs)
        qs.update(assigned_to=agent)

        msg.refresh_from_db()
        assert msg.assigned_to == agent
        assert "sla_state" not in msg.extra
