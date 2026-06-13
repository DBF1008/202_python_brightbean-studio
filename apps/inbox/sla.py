"""Centralised SLA state for inbox messages (F-3.1).

The SLA "cycle" of a message is stored in two ``extra`` keys so that the
background worker, the views (reopen / reassign / reply) and the UI all share a
single, repeatable definition of "is this message overdue and who should hear
about it":

* ``sla_started_at`` -- ISO timestamp marking the start of the current pending
  cycle. It is (re)set when a message first arrives and whenever it transitions
  *back* into a pending state (reopen). Its absence means "fall back to
  ``received_at``" so legacy rows keep working.
* ``sla_notified`` -- ``True`` once an overdue notification has been sent for the
  current cycle + owner. It is cleared on reopen, on reassignment, and by the
  worker whenever the message is no longer overdue (e.g. the SLA target was
  lengthened), which is what lets overdue alerts re-trigger.

The deadline itself is never frozen: the worker computes ``anchor + current
target`` on every pass, so configuration changes take effect immediately.
"""

from datetime import datetime, timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import InboxMessage

SLA_STARTED_KEY = "sla_started_at"
SLA_NOTIFIED_KEY = "sla_notified"

# A message is SLA-tracked only while it is awaiting a response.
PENDING_STATUSES = frozenset({InboxMessage.Status.UNREAD, InboxMessage.Status.OPEN})


def is_pending(message: InboxMessage) -> bool:
    """Whether the message is in a status that the SLA should track."""
    return message.status in PENDING_STATUSES


def sla_anchor(message: InboxMessage) -> datetime:
    """Effective start of the current SLA cycle.

    Uses ``sla_started_at`` when present (set on arrival / reopen) and falls back
    to ``received_at`` for legacy rows that pre-date cycle tracking.
    """
    raw = message.extra.get(SLA_STARTED_KEY)
    if raw:
        parsed = parse_datetime(raw)
        if parsed is not None:
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed)
            return parsed
    return message.received_at


def sla_deadline(message: InboxMessage, config) -> datetime:
    """When the current cycle becomes overdue under the *current* config."""
    return sla_anchor(message) + timedelta(minutes=config.target_response_minutes)


def is_overdue(message: InboxMessage, config, now: datetime | None = None) -> bool:
    """True if the message has passed its (dynamically computed) deadline."""
    now = now or timezone.now()
    return now >= sla_deadline(message, config)


def arm_sla(message: InboxMessage, anchor: datetime | None = None) -> None:
    """Begin (or restart) an SLA cycle.

    Sets a fresh anchor and clears the notified flag so the current owner can be
    alerted. ``anchor`` defaults to now; pass ``received_at`` for brand-new
    messages so the clock starts when the customer actually reached out.
    """
    message.extra[SLA_STARTED_KEY] = (anchor or timezone.now()).isoformat()
    message.extra.pop(SLA_NOTIFIED_KEY, None)


def clear_sla(message: InboxMessage) -> None:
    """Stop tracking the message (it left a pending status)."""
    message.extra.pop(SLA_STARTED_KEY, None)
    message.extra.pop(SLA_NOTIFIED_KEY, None)


def mark_notified(message: InboxMessage) -> None:
    """Record that the current cycle's overdue alert has been delivered."""
    message.extra[SLA_NOTIFIED_KEY] = True


def clear_notified(message: InboxMessage) -> bool:
    """Drop the notified flag. Returns True if anything changed."""
    return message.extra.pop(SLA_NOTIFIED_KEY, None) is not None


def is_notified(message: InboxMessage) -> bool:
    return bool(message.extra.get(SLA_NOTIFIED_KEY))


def transition_status(message: InboxMessage, new_status: str) -> bool:
    """Apply a status change and the SLA side-effects it implies.

    * non-pending -> pending (reopen): start a fresh cycle.
    * pending -> non-pending (resolve / archive): stop tracking.
    * pending -> pending (e.g. unread -> open): no SLA change.

    Mutates ``message.status`` and ``message.extra`` in place and returns whether
    ``extra`` changed (so the caller can decide whether to persist it).
    """
    old_status = message.status
    message.status = new_status

    was_pending = old_status in PENDING_STATUSES
    now_pending = new_status in PENDING_STATUSES

    if now_pending and not was_pending:
        arm_sla(message)
        return True
    if was_pending and not now_pending:
        clear_sla(message)
        return True
    return False


def on_reassign(message: InboxMessage) -> bool:
    """Re-arm the overdue alert for a newly assigned owner.

    The clock is intentionally *not* reset -- reassigning does not grant a fresh
    response window -- but the notified flag is cleared so the latest owner is
    alerted on the next worker pass. Returns whether ``extra`` changed.
    """
    if not is_pending(message):
        return False
    return clear_notified(message)
