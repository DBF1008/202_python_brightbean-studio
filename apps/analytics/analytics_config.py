"""Settings-driven analytics configuration.

Resolves analytics sync cadence, backfill windows and freshness intervals
through the workspace → org → app-default cascade exposed by
:func:`apps.settings_manager.helpers.get_setting`.

The :class:`AnalyticsConfig` dataclass is the **single source of truth**
consumed by both the background sync worker (``tasks.py``) and the
freshness helpers (``freshness.py``) so that the ``next_sync_eta`` the
API exposes to agents is always computed from the same cadence table the
worker actually executes — no drift.

Typical usage::

    from apps.analytics.analytics_config import resolve_analytics_config

    cfg = resolve_analytics_config(account.workspace_id,
                                   account.workspace.organization_id)
    interval = cfg.post_sync_interval(post_age)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from apps.settings_manager.helpers import get_setting

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_cadence(raw: Any) -> tuple[tuple[timedelta, timedelta], ...]:
    """Parse ``[[max_age_days, interval_hours], ...]`` into timedelta pairs.

    The app default in ``defaults.py`` stores the cadence ladder as a JSON
    array of ``[days, hours]`` pairs — easy for admins to edit in a settings
    UI.  This function converts to the ``tuple[tuple[timedelta, timedelta], ...]``
    format the interval lookup expects.
    """
    if not raw:
        return ()
    out: list[tuple[timedelta, timedelta]] = []
    for entry in raw:
        try:
            max_age_days, interval_hours = entry[0], entry[1]
            out.append((timedelta(days=max_age_days), timedelta(hours=interval_hours)))
        except (TypeError, ValueError, IndexError):
            continue
    return tuple(out)


def _parse_backfill_map(raw: Any) -> dict[str, int]:
    """Parse a ``{platform: days}`` dict from a JSON setting value."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for platform, days in raw.items():
        try:
            out[str(platform)] = int(days)
        except (TypeError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalyticsConfig:
    """Resolved analytics settings for one workspace.

    All intervals are :class:`datetime.timedelta` instances so callers never
    need to remember whether a field is seconds, minutes, hours or days.

    The cadence table and backfill map are frozen at construction time —
    mutating settings mid-sync would break the no-drift guarantee.
    """

    # Post-sync cadence: ``((max_age, interval), ...)`` sorted by max_age.
    # Posts older than the last entry's max_age are no longer synced.
    post_sync_cadence: tuple[tuple[timedelta, timedelta], ...]

    # How often account-level metrics are synced.
    account_sync_interval: timedelta

    # Sentinel delay for just-connected / just-published targets.
    first_poll_delay: timedelta

    # Default backfill window (days) on connect / reconnect.
    backfill_days_default: int

    # Per-platform backfill overrides.  ``0`` → skip (no analytics surface).
    backfill_days_per_platform: dict[str, int] = field(default_factory=dict)

    # Number of recent days to walk back when syncing account-level metrics.
    account_metrics_recent_days: int = 3

    # -- convenience API --------------------------------------------------

    def post_sync_interval(self, age: timedelta) -> timedelta | None:
        """Return the sync interval for a post of the given ``age``.

        ``None`` means the post is past the horizon and the background sync
        no longer refreshes it.  Shared between the sync loop
        (``_post_cadence_due``) and the freshness helpers — both call *this*
        method on the same :class:`AnalyticsConfig`, so they cannot drift.
        """
        for max_age, interval in self.post_sync_cadence:
            if age < max_age:
                return interval
        return None

    @property
    def post_max_age(self) -> timedelta:
        """Max post age beyond which syncs stop (last cadence row's max_age)."""
        if self.post_sync_cadence:
            return self.post_sync_cadence[-1][0]
        return timedelta(days=90)

    def backfill_cap_for(self, platform: str) -> int:
        """Return the backfill window (days) for ``platform``.

        Falls back to :attr:`backfill_days_default` when the platform has
        no explicit entry.  A return value of ``0`` means the platform has
        no analytics surface — the caller should skip API calls entirely.
        """
        return self.backfill_days_per_platform.get(platform, self.backfill_days_default)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def resolve_analytics_config(
    workspace_id,
    workspace_org_id=None,
) -> AnalyticsConfig:
    """Resolve the full :class:`AnalyticsConfig` for a workspace.

    Follows the workspace → org → app-default cascade via
    :func:`~apps.settings_manager.helpers.get_setting`.  Call once per
    account (or per sync batch) and reuse the result — the dataclass is
    frozen so it's safe to share across the sync loop's iterations.

    ``workspace_org_id`` is forwarded to :func:`get_setting` to avoid an
    extra workspace → org lookup query when the caller already has it.
    """
    kw = {"workspace_id": workspace_id, "workspace_org_id": workspace_org_id}

    cadence_raw = get_setting(workspace_id, "analytics.post_sync_cadence", workspace_org_id)
    account_hours = get_setting(workspace_id, "analytics.account_sync_interval_hours", workspace_org_id)
    first_poll_min = get_setting(workspace_id, "analytics.first_poll_delay_minutes", workspace_org_id)
    backfill_default = get_setting(workspace_id, "analytics.backfill_days_default", workspace_org_id)
    backfill_map_raw = get_setting(workspace_id, "analytics.backfill_days_per_platform", workspace_org_id)
    recent_days = get_setting(workspace_id, "analytics.account_metrics_recent_days", workspace_org_id)

    return AnalyticsConfig(
        post_sync_cadence=_parse_cadence(cadence_raw),
        account_sync_interval=timedelta(hours=float(account_hours or 24)),
        first_poll_delay=timedelta(minutes=float(first_poll_min or 5)),
        backfill_days_default=int(backfill_default or 90),
        backfill_days_per_platform=_parse_backfill_map(backfill_map_raw),
        account_metrics_recent_days=int(recent_days or 3),
    )
