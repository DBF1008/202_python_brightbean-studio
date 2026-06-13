"""Tests for the settings-driven analytics cadence resolver.

Covers :mod:`apps.analytics.cadence` and the no-drift contract between the
background sync worker (``apps.analytics.tasks._post_cadence_due``) and the
agent-API freshness helper (``apps.analytics.freshness.post_freshness``): both
resolve cadence through the *same* settings cascade, so the schedule the worker
runs and the ``next_sync_eta`` the API advertises cannot diverge.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

# Every test touches the DB (settings rows, accounts, posts, snapshots).
pytestmark = pytest.mark.django_db

# Application defaults (apps/settings_manager/defaults.py) — the baseline the
# cascade falls back to when no workspace/org override exists.
_DEFAULT_HIGH_FREQ_HOURS = 48
_DEFAULT_LOOKBACK_DAYS = 90

_HIGH_FREQ_KEY = "analytics.high_frequency_collection_hours"
_LOOKBACK_KEY = "analytics.optimal_time_lookback_days"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organization(db):
    from apps.organizations.models import Organization

    return Organization.objects.create(name="Cadence Org")


@pytest.fixture
def workspace(db, organization):
    from apps.workspaces.models import Workspace

    return Workspace.objects.create(name="Cadence WS", organization=organization)


@pytest.fixture
def instagram_account(db, workspace):
    """Instagram — full analytics surface, 90-day platform cap."""
    from apps.social_accounts.models import SocialAccount

    return SocialAccount.objects.create(
        workspace=workspace,
        platform="instagram",
        account_platform_id="ig-cadence",
        account_name="IG Cadence",
        connection_status="connected",
    )


def _make_published_post(workspace, account, *, published_ago: timedelta, seed_snapshot: bool = True):
    """Create a published ``PlatformPost`` aged ``published_ago`` in the past.

    Optionally seeds a single ``PostInsightsSnapshot`` so ``post_freshness``
    has a ``captured_at`` to anchor its ETA on. ``captured_at`` is ``auto_now``,
    so the seeded row's timestamp is "now" — exactly what a fresh sync writes.
    """
    from apps.analytics.models import PostInsightsSnapshot
    from apps.composer.models import PlatformPost, Post

    post = Post.objects.create(workspace=workspace, caption="cadence post")
    pp = PlatformPost.objects.create(
        post=post,
        social_account=account,
        status="published",
        published_at=timezone.now() - published_ago,
        platform_post_id="ig-shortcode-cadence",
    )
    if seed_snapshot:
        PostInsightsSnapshot.objects.create(
            platform_post=pp,
            metric_key="likes",
            date=timezone.now().date(),
            value=10.0,
        )
    return post, pp


# ---------------------------------------------------------------------------
# 1. Settings cascade: workspace > org > app default
# ---------------------------------------------------------------------------


def test_cascade_workspace_beats_org_beats_default(workspace, organization):
    from apps.analytics.cadence import resolve_cadence
    from apps.settings_manager.models import OrgSetting, WorkspaceSetting

    # No overrides → app defaults.
    c = resolve_cadence(workspace.id, organization.id)
    assert c.high_frequency_hours == _DEFAULT_HIGH_FREQ_HOURS
    assert c.lookback_days == _DEFAULT_LOOKBACK_DAYS

    # Org override beats the app default.
    OrgSetting.objects.create(organization=organization, key=_HIGH_FREQ_KEY, value=24)
    OrgSetting.objects.create(organization=organization, key=_LOOKBACK_KEY, value=60)
    c = resolve_cadence(workspace.id, organization.id)
    assert c.high_frequency_hours == 24
    assert c.lookback_days == 60

    # Workspace override beats the org override (only for the key it sets).
    WorkspaceSetting.objects.create(workspace=workspace, key=_HIGH_FREQ_KEY, value=12)
    c = resolve_cadence(workspace.id, organization.id)
    assert c.high_frequency_hours == 12
    assert c.lookback_days == 60  # still inherited from the org


def test_invalid_override_falls_back_to_default(workspace, organization):
    """A non-int / non-positive stored JSON override falls back to the default."""
    from apps.analytics.cadence import resolve_cadence
    from apps.settings_manager.models import WorkspaceSetting

    WorkspaceSetting.objects.create(workspace=workspace, key=_HIGH_FREQ_KEY, value="not-a-number")
    WorkspaceSetting.objects.create(workspace=workspace, key=_LOOKBACK_KEY, value=0)
    c = resolve_cadence(workspace.id, organization.id)
    assert c.high_frequency_hours == _DEFAULT_HIGH_FREQ_HOURS  # bad string → default
    assert c.lookback_days == _DEFAULT_LOOKBACK_DAYS  # 0 (≤0) → default


def test_resolve_cadence_for_account_uses_account_workspace(instagram_account):
    """The account convenience wrapper resolves via the account's workspace/org."""
    from apps.analytics.cadence import resolve_cadence_for_account
    from apps.settings_manager.models import WorkspaceSetting

    WorkspaceSetting.objects.create(
        workspace=instagram_account.workspace, key=_HIGH_FREQ_KEY, value=6
    )
    c = resolve_cadence_for_account(instagram_account)
    assert c.high_frequency_hours == 6


# ---------------------------------------------------------------------------
# 2. The high-frequency window drives the hourly (tier-1) rung
# ---------------------------------------------------------------------------


def test_high_frequency_window_drives_hourly_tier(workspace, instagram_account):
    from apps.analytics.cadence import resolve_cadence_for_account
    from apps.settings_manager.models import WorkspaceSetting

    # Default 48h: 36h in → hourly; 50h in → past the window → 6-hourly.
    c = resolve_cadence_for_account(instagram_account)
    assert c.post_sync_interval(timedelta(hours=36), "instagram") == timedelta(hours=1)
    assert c.post_sync_interval(timedelta(hours=50), "instagram") == timedelta(hours=6)

    # A workspace override of 12h flips the same 36h post to the 6-hour rung.
    WorkspaceSetting.objects.create(workspace=workspace, key=_HIGH_FREQ_KEY, value=12)
    c = resolve_cadence_for_account(instagram_account)
    assert c.post_sync_interval(timedelta(hours=10), "instagram") == timedelta(hours=1)
    assert c.post_sync_interval(timedelta(hours=36), "instagram") == timedelta(hours=6)


def test_ladder_tiers_at_defaults(instagram_account):
    """Full default ladder for a 90-day-capable platform."""
    from apps.analytics.cadence import resolve_cadence_for_account

    c = resolve_cadence_for_account(instagram_account)
    assert c.post_sync_interval(timedelta(hours=1), "instagram") == timedelta(hours=1)
    assert c.post_sync_interval(timedelta(days=3), "instagram") == timedelta(hours=6)
    assert c.post_sync_interval(timedelta(days=10), "instagram") == timedelta(days=1)
    assert c.post_sync_interval(timedelta(days=60), "instagram") == timedelta(days=7)
    assert c.post_sync_interval(timedelta(days=90), "instagram") is None


# ---------------------------------------------------------------------------
# 3. The lookback setting drives the stop horizon (worker + freshness agree)
# ---------------------------------------------------------------------------


def test_lookback_sets_stop_horizon(workspace, instagram_account):
    from apps.analytics.cadence import resolve_cadence_for_account
    from apps.analytics.freshness import post_freshness
    from apps.analytics.tasks import _post_cadence_due
    from apps.settings_manager.models import WorkspaceSetting

    WorkspaceSetting.objects.create(workspace=workspace, key=_LOOKBACK_KEY, value=30)
    _post, pp = _make_published_post(workspace, instagram_account, published_ago=timedelta(days=40))

    cadence = resolve_cadence_for_account(instagram_account)
    # Past the 30-day horizon on all three surfaces:
    assert cadence.post_sync_interval(timedelta(days=40), "instagram") is None
    assert _post_cadence_due(pp, platform="instagram", cadence=cadence) is False
    _captured, eta = post_freshness(pp)
    assert eta is None


# ---------------------------------------------------------------------------
# 4. No drift: the advertised ETA equals the interval the worker would use
# ---------------------------------------------------------------------------


def test_freshness_eta_matches_worker_interval(workspace, instagram_account):
    """``next_sync_eta`` == last_captured_at + the exact worker interval."""
    from apps.analytics.cadence import resolve_cadence_for_account
    from apps.analytics.freshness import post_freshness

    # 6h-old post, default 48h high-freq window → tier-1 hourly, well clear of
    # any tier boundary so the comparison is timing-stable.
    _post, pp = _make_published_post(workspace, instagram_account, published_ago=timedelta(hours=6))

    captured, eta = post_freshness(pp)
    assert captured is not None

    cadence = resolve_cadence_for_account(instagram_account)
    age = timezone.now() - pp.published_at
    expected_interval = cadence.post_sync_interval(age, "instagram")
    assert expected_interval == timedelta(hours=1)
    assert eta == captured + expected_interval


def test_no_rows_yet_uses_first_poll_delay(workspace, instagram_account):
    """A published post with no snapshots polls back via the first-poll delay."""
    from apps.analytics.cadence import FIRST_POLL_DELAY
    from apps.analytics.freshness import post_freshness

    before = timezone.now()
    _post, pp = _make_published_post(
        workspace, instagram_account, published_ago=timedelta(hours=6), seed_snapshot=False
    )
    captured, eta = post_freshness(pp)
    assert captured is None
    # ETA is ~now + FIRST_POLL_DELAY (min of the 1h interval and the 5-min delay).
    assert before + FIRST_POLL_DELAY <= eta <= timezone.now() + FIRST_POLL_DELAY


# ---------------------------------------------------------------------------
# 5. Backfill window = configured lookback, capped by platform capability
# ---------------------------------------------------------------------------


def test_backfill_window_capped_per_platform(workspace, organization):
    from apps.analytics.cadence import resolve_cadence
    from apps.settings_manager.models import WorkspaceSetting

    # Default lookback 90: instagram=90, tiktok capped at 60, no-analytics=0.
    c = resolve_cadence(workspace.id, organization.id)
    assert c.backfill_window_days("instagram") == 90
    assert c.backfill_window_days("tiktok") == 60
    assert c.backfill_window_days("bluesky") == 0
    assert c.backfill_window_days("mastodon") == 0
    assert c.backfill_window_days("linkedin_personal") == 0

    # Lookback 30 (below both caps): instagram and tiktok both clamp to 30.
    WorkspaceSetting.objects.create(workspace=workspace, key=_LOOKBACK_KEY, value=30)
    c = resolve_cadence(workspace.id, organization.id)
    assert c.backfill_window_days("instagram") == 30
    assert c.backfill_window_days("tiktok") == 30
    assert c.backfill_window_days("bluesky") == 0  # still skipped


def test_unknown_platform_uses_default_cap(workspace, organization):
    from apps.analytics.cadence import resolve_cadence

    c = resolve_cadence(workspace.id, organization.id)  # lookback 90
    # An unmapped platform falls back to DEFAULT_PLATFORM_MAX_BACKFILL_DAYS (90).
    assert c.backfill_window_days("some_future_platform") == 90
