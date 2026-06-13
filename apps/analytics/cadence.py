"""Single source of truth for analytics collection cadence + backfill window.

Both the background sync worker (``apps/analytics/tasks.py``) and the agent-API
freshness helpers (``apps/analytics/freshness.py``) resolve cadence through this
module, so the cadence the worker *actually* runs and the ``next_sync_eta`` the
API/MCP surfaces advertise cannot drift apart.

Two knobs are settings-driven via the cascade
(:func:`apps.settings_manager.helpers.get_setting`, workspace → org → app
default):

* ``analytics.high_frequency_collection_hours`` — how long after publish a post
  is collected hourly (the first rung of the decay ladder).
* ``analytics.optimal_time_lookback_days`` — how far back we collect/keep
  syncing a post; also the ladder's stop horizon and the backfill window.

The remaining values (first-poll delay, account-sync interval, account
"recent days" depth, per-platform capability caps) have no reserved setting key,
so they live here as plain constants — centralized purely so the two consumers
share one definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from apps.settings_manager.defaults import APP_DEFAULTS
from apps.settings_manager.helpers import get_setting

# Setting keys (the only two analytics knobs wired today).
_HIGH_FREQ_KEY = "analytics.high_frequency_collection_hours"
_LOOKBACK_KEY = "analytics.optimal_time_lookback_days"

# Centralized non-configurable constants (shared by tasks.py + freshness.py).
#
# Sentinel poll delay for a just-connected account / just-published post that has
# no snapshot rows yet — the agent should poll back soon, not wait a full day.
FIRST_POLL_DELAY = timedelta(minutes=5)
# Account-level metrics are collected at most once per day. The worker enforces
# this by skipping accounts that already have today's row; freshness advertises
# the same interval so the two agree.
ACCOUNT_SYNC_INTERVAL = timedelta(hours=24)
# Recent days to attempt when syncing account-level metrics (covers providers
# whose Analytics API lags 1-2 days, e.g. YouTube). Days with rows are skipped.
ACCOUNT_METRICS_RECENT_DAYS = 3

# Per-platform *capability* cap (days) — the maximum history the platform's API
# can actually return on connect. The effective backfill/collection window is the
# configured lookback capped by this. Platforms with no analytics surface are 0
# (their NO_ANALYTICS_PLATFORMS entry must keep this at 0 — see
# ``apps/analytics/constants.py``).
DEFAULT_PLATFORM_MAX_BACKFILL_DAYS = 90
PLATFORM_MAX_BACKFILL_DAYS: dict[str, int] = {
    "facebook": 90,
    "instagram": 90,
    "instagram_login": 90,
    "linkedin_company": 90,
    "youtube": 90,
    "pinterest": 90,
    "threads": 90,
    "google_business": 90,
    "tiktok": 60,
    # Bluesky / Mastodon / LinkedIn-Personal have no analytics surface — skip.
    # LinkedIn only exposes share statistics for Organization URNs, not personal
    # Person URNs, regardless of granted scopes.
    "bluesky": 0,
    "mastodon": 0,
    "linkedin_personal": 0,
}


@dataclass(frozen=True)
class AnalyticsCadence:
    """Resolved analytics cadence for one workspace.

    ``post_sync_interval`` is the single decay ladder consumed by both the sync
    loop (``apps.analytics.tasks._post_cadence_due``) and the agent-API freshness
    helper (``apps.analytics.freshness.post_freshness``).
    """

    high_frequency_hours: int  # analytics.high_frequency_collection_hours
    lookback_days: int  # analytics.optimal_time_lookback_days

    def backfill_window_days(self, platform: str) -> int:
        """Effective collection window (days) for ``platform``.

        The configured lookback, capped by what the platform's API can return.
        ``0`` for platforms without an analytics surface (backfill is skipped).
        """
        cap = PLATFORM_MAX_BACKFILL_DAYS.get(platform, DEFAULT_PLATFORM_MAX_BACKFILL_DAYS)
        return min(self.lookback_days, cap)

    def post_sync_interval(self, age: timedelta, platform: str) -> timedelta | None:
        """Return the sync interval for a post of ``age`` on ``platform``.

        ``None`` means the post is past the collection horizon and the
        background sync no longer refreshes it.

        The stop horizon is the **per-platform** backfill window
        (``min(lookback, platform_cap)``) — the same value that bounds the
        worker's candidate query and the on-connect backfill. Tying all three to
        one number is what prevents the worker from stopping while the API still
        advertises a future ETA (e.g. TikTok's 60-day cap under a 90-day
        lookback). The ``min(..., horizon)`` guards keep the ladder monotonic for
        any combination of setting values (e.g. a high-frequency window larger
        than 7 days simply absorbs the 6-hour rung).
        """
        horizon = timedelta(days=self.backfill_window_days(platform))
        if age >= horizon:
            return None
        if age < min(timedelta(hours=self.high_frequency_hours), horizon):
            return timedelta(hours=1)
        if age < min(timedelta(days=7), horizon):
            return timedelta(hours=6)
        if age < min(timedelta(days=30), horizon):
            return timedelta(days=1)
        return timedelta(days=7)


def _as_positive_int(value: object, default: int) -> int:
    """Coerce a stored JSON setting to a positive int, else fall back.

    Settings are JSON, so a workspace/org override could be a string, float,
    ``None``, or a nonsensical ≤0 value. Any of those falls back to the app
    default rather than crashing the worker.
    """
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return n if n > 0 else default


def resolve_cadence(workspace_id, organization_id=None) -> AnalyticsCadence:
    """Resolve the analytics cadence for a workspace via the settings cascade.

    ``organization_id`` is resolved once (if not supplied) and reused for both
    lookups so we don't repeat the workspace→org query per key.
    """
    if organization_id is None:
        from apps.workspaces.models import Workspace

        organization_id = (
            Workspace.objects.filter(id=workspace_id).values_list("organization_id", flat=True).first()
        )
    high_freq = get_setting(workspace_id, _HIGH_FREQ_KEY, organization_id)
    lookback = get_setting(workspace_id, _LOOKBACK_KEY, organization_id)
    return AnalyticsCadence(
        high_frequency_hours=_as_positive_int(high_freq, APP_DEFAULTS[_HIGH_FREQ_KEY]),
        lookback_days=_as_positive_int(lookback, APP_DEFAULTS[_LOOKBACK_KEY]),
    )


def resolve_cadence_for_account(account) -> AnalyticsCadence:
    """Resolve cadence for a ``SocialAccount``.

    Uses the account's cached workspace (the sync worker selects it via
    ``select_related("workspace")``, so this adds no query there).
    """
    return resolve_cadence(account.workspace_id, account.workspace.organization_id)
