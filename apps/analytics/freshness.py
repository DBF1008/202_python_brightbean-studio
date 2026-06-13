"""Freshness helpers for analytics API responses.

Computes ``(captured_at, next_sync_eta)`` for the agent-facing analytics
endpoints. ``captured_at`` is the most-recent snapshot row touched for the
target; ``next_sync_eta`` mirrors the background sync cadence in
``apps/analytics/tasks.py`` so callers can pick a sensible poll delay.

Both this module and the sync worker resolve their cadence / interval
values through the *same* :class:`~apps.analytics.analytics_config.AnalyticsConfig`
— resolved from the account's workspace via the settings cascade — so the
``next_sync_eta`` the API exposes to agents can never drift from what the
worker actually executes.

These helpers are intentionally separated from ``apps/analytics/services.py``
because that module is consumed by Django templates today and stays
rendering-agnostic.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Max
from django.utils import timezone

from apps.composer.models import PlatformPost
from apps.social_accounts.models import SocialAccount

from .analytics_config import AnalyticsConfig, resolve_analytics_config
from .constants import NO_ANALYTICS_PLATFORMS
from .models import AccountInsightsSnapshot, PostInsightsSnapshot


def _resolve_config_for_account(account: SocialAccount) -> AnalyticsConfig:
    """Resolve the analytics config from an account's workspace relationship.

    ``SocialAccount`` always has a FK to ``Workspace``; we forward
    ``organization_id`` to :func:`resolve_analytics_config` so it can skip
    the workspace → org lookup query.  ``select_related("workspace")`` on
    the queryset avoids an extra round-trip.
    """
    return resolve_analytics_config(account.workspace_id, account.workspace.organization_id)


def account_freshness(
    account: SocialAccount,
    *,
    last_captured_at: datetime | None = None,
    have_last_captured_at: bool = False,
    config: AnalyticsConfig | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Return ``(captured_at, next_sync_eta)`` for an account.

    * ``(None, None)`` for platforms in :data:`NO_ANALYTICS_PLATFORMS` — no
      background sync is scheduled and no snapshots will ever land.
    * ``(None, now + first_poll_delay)`` for an account that has been
      connected but hasn't been synced yet, so the agent polls back shortly.
    * ``(last, last + account_sync_interval)`` once any account-level
      snapshot exists.

    Both ``first_poll_delay`` and ``account_sync_interval`` are resolved
    through the workspace settings cascade (via ``config`` or auto-resolved
    from the account's workspace), matching the worker's behavior exactly.

    Callers that have already touched the snapshots table (e.g. via
    :func:`apps.analytics.services.account_analytics_bundle`) can pass
    the latest ``captured_at`` they observed via ``last_captured_at`` and
    set ``have_last_captured_at=True`` to skip the redundant ``Max``
    aggregate query. ``have_last_captured_at`` disambiguates "no
    snapshots yet" from "caller didn't check".

    ``config`` may be supplied by callers that have already resolved the
    :class:`AnalyticsConfig` to avoid a redundant cascade lookup.
    """
    if account.platform in NO_ANALYTICS_PLATFORMS:
        return None, None
    cfg = config or _resolve_config_for_account(account)
    if have_last_captured_at:
        last = last_captured_at
    else:
        last = AccountInsightsSnapshot.objects.filter(social_account=account).aggregate(latest=Max("captured_at"))[
            "latest"
        ]
    if last is None:
        return None, timezone.now() + cfg.first_poll_delay
    return last, last + cfg.account_sync_interval


def post_freshness(
    platform_post: PlatformPost,
    *,
    last_captured_at: datetime | None = None,
    have_last_captured_at: bool = False,
    config: AnalyticsConfig | None = None,
) -> tuple[datetime | None, datetime | None]:
    """Return ``(captured_at, next_sync_eta)`` for a per-platform post.

    The cadence ladder is :meth:`AnalyticsConfig.post_sync_interval` —
    called on the *same* resolved config the sync worker uses — so this
    helper and the sync loop **cannot drift**.

    Drafts / scheduled posts (no ``published_at``) and posts on platforms
    without an analytics surface return ``(None, None)``.

    Callers that have already fetched snapshot rows (e.g. via
    :func:`apps.analytics.services.post_detail`) can pass the latest
    ``captured_at`` they observed via ``last_captured_at`` to skip the
    extra ``Max`` aggregate query. Pass ``have_last_captured_at=True`` to
    signal that the caller's lookup was authoritative — otherwise the
    helper will fall back to its own query (``None`` is ambiguous: it
    could mean "no snapshots" OR "caller didn't check").

    ``config`` may be supplied by callers that have already resolved the
    :class:`AnalyticsConfig` to avoid a redundant cascade lookup.
    """
    if platform_post.social_account.platform in NO_ANALYTICS_PLATFORMS:
        return None, None
    if not platform_post.published_at:
        return None, None

    cfg = config or resolve_analytics_config(
        platform_post.social_account.workspace_id,
        platform_post.social_account.workspace.organization_id,
    )

    if have_last_captured_at:
        last = last_captured_at
    else:
        last = PostInsightsSnapshot.objects.filter(platform_post=platform_post).aggregate(latest=Max("captured_at"))[
            "latest"
        ]
    age = timezone.now() - platform_post.published_at
    interval = cfg.post_sync_interval(age)
    if interval is None:
        # Past horizon: syncs have stopped, so there is no meaningful next
        # ETA even if ``last`` exists from earlier in the post's life.
        return last, None
    # If no rows yet, poll back sooner than the cadence would otherwise
    # suggest — we want the first-sync delay to drive the next ETA.
    if last is None:
        return None, timezone.now() + min(interval, cfg.first_poll_delay)
    return last, last + interval
