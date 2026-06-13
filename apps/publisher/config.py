"""Resolution of publisher behavior from the settings cascade.

The publishing engine's runtime behavior — first-comment delay, retry attempts,
retry backoff schedule, and the global publish-batch size — is configurable per
workspace (with org and application-default fallbacks) via ``settings_manager``.

This module owns the *meaning* of those settings (parsing, coercion, fallbacks)
so the engine can stay focused on the publish loop. It deliberately does not
import the engine, to avoid an import cycle.

Cascade keys (see ``apps/settings_manager/defaults.py``):

- ``publishing.first_comment_delay_seconds``   (per workspace)
- ``publishing.retry_max_attempts``            (per workspace)
- ``publishing.retry_backoff_schedule``        (per workspace, e.g. "1min,5min,30min")
- ``infra.max_concurrent_publish_jobs``        (global / app-default tier only)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from apps.settings_manager.helpers import get_global_setting, get_setting

logger = logging.getLogger(__name__)

# Canonical fallback defaults. These mirror APP_DEFAULTS and are used whenever a
# cascade lookup is missing or a stored override cannot be parsed.
DEFAULT_FIRST_COMMENT_DELAY = 120
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = [60, 300, 1800]  # 1min, 5min, 30min
DEFAULT_MAX_CONCURRENT_PUBLISH_JOBS = 10

# Settings keys.
KEY_FIRST_COMMENT_DELAY = "publishing.first_comment_delay_seconds"
KEY_RETRY_MAX_ATTEMPTS = "publishing.retry_max_attempts"
KEY_RETRY_BACKOFF = "publishing.retry_backoff_schedule"
KEY_MAX_CONCURRENT_PUBLISH_JOBS = "infra.max_concurrent_publish_jobs"

# Duration unit -> seconds multiplier, for parse_backoff_schedule.
_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
}

_DURATION_RE = re.compile(r"^(\d+)\s*([a-z]*)$")


def _parse_duration_token(token) -> int | None:
    """Parse a single duration token (e.g. "5min", "30s", "120") to seconds.

    A bare number is treated as seconds. Returns ``None`` for anything that is
    not a positive duration (unknown unit, zero, negative, or garbage).
    """
    if isinstance(token, bool):
        return None
    if isinstance(token, (int, float)):
        seconds = int(token)
        return seconds if seconds > 0 else None
    if not isinstance(token, str):
        return None
    match = _DURATION_RE.match(token.strip().lower())
    if not match:
        return None
    value, unit = match.groups()
    multiplier = 1 if unit == "" else _UNIT_SECONDS.get(unit)
    if multiplier is None:
        return None
    seconds = int(value) * multiplier
    return seconds if seconds > 0 else None


def parse_backoff_schedule(value) -> list[int]:
    """Parse a retry backoff schedule into a list of positive second-delays.

    Accepts the spec string form (``"1min,5min,30min"``) or an already-parsed
    list (a JSON override may store either). Unparseable / non-positive tokens
    are skipped; if nothing valid remains, falls back to
    ``DEFAULT_RETRY_BACKOFF``.
    """
    if value is None:
        return list(DEFAULT_RETRY_BACKOFF)
    if isinstance(value, str):
        tokens: list = value.split(",")
    elif isinstance(value, (list, tuple)):
        tokens = list(value)
    else:
        tokens = [value]

    parsed = [seconds for seconds in (_parse_duration_token(t) for t in tokens) if seconds is not None]

    if not parsed:
        logger.warning("Unparseable retry_backoff_schedule %r; using default", value)
        return list(DEFAULT_RETRY_BACKOFF)
    return parsed


def _coerce_int(value, default, *, minimum) -> int:
    """Coerce ``value`` to an int >= ``minimum``, else return ``default``."""
    if isinstance(value, bool):
        return default
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result >= minimum else default


@dataclass(frozen=True)
class PublishConfig:
    """Resolved publishing behavior for a single workspace."""

    first_comment_delay: int
    retry_max_attempts: int
    retry_backoff: list[int]


def resolve_publish_config(workspace_id, workspace_org_id=None) -> PublishConfig:
    """Resolve per-workspace publishing config via the settings cascade.

    Each key falls back independently: workspace override -> org override ->
    application default (and an unparseable stored value falls back to the
    canonical default for that key).
    """
    first_comment_delay = _coerce_int(
        get_setting(workspace_id, KEY_FIRST_COMMENT_DELAY, workspace_org_id),
        DEFAULT_FIRST_COMMENT_DELAY,
        minimum=0,
    )
    retry_max_attempts = _coerce_int(
        get_setting(workspace_id, KEY_RETRY_MAX_ATTEMPTS, workspace_org_id),
        DEFAULT_MAX_RETRIES,
        minimum=0,
    )
    retry_backoff = parse_backoff_schedule(get_setting(workspace_id, KEY_RETRY_BACKOFF, workspace_org_id))
    return PublishConfig(
        first_comment_delay=first_comment_delay,
        retry_max_attempts=retry_max_attempts,
        retry_backoff=retry_backoff,
    )


def resolve_publish_config_for(platform_post) -> PublishConfig:
    """Resolve publishing config for a ``PlatformPost`` via its workspace.

    Callers should ``select_related("post__workspace")`` to avoid extra queries.
    """
    workspace = platform_post.post.workspace
    return resolve_publish_config(workspace.id, workspace.organization_id)


def resolve_max_concurrent_publish_jobs() -> int:
    """Resolve the global publish-batch size (application-default tier only)."""
    return _coerce_int(
        get_global_setting(KEY_MAX_CONCURRENT_PUBLISH_JOBS),
        DEFAULT_MAX_CONCURRENT_PUBLISH_JOBS,
        minimum=1,
    )
