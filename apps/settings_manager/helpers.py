"""Settings cascade helper: workspace -> org -> app default."""

import logging
import re

from .defaults import APP_DEFAULTS
from .models import OrgSetting, WorkspaceSetting

logger = logging.getLogger(__name__)

# Hardcoded safe fallback — avoids circular reliance on APP_DEFAULTS parsing.
_BACKOFF_FALLBACK = [60, 300, 1800]  # 1min, 5min, 30min

_UNIT_MAP = {"s": 1, "sec": 1, "min": 60, "h": 3600, "hr": 3600}
_TOKEN_RE = re.compile(r"(\d+)\s*(s|sec|min|h|hr)?", re.IGNORECASE)


def parse_backoff_schedule(raw, *, fallback=None):
    """Parse a backoff schedule string into a list of seconds.

    Accepted formats per token: ``"60"``, ``"60s"``, ``"1min"``, ``"5h"``.
    A bare list (from a JSON-field override) is coerced to ints directly.

    On any parse error the *fallback* is returned (defaulting to
    ``[60, 300, 1800]``).
    """
    if isinstance(raw, (list, tuple)):
        try:
            return [int(v) for v in raw]
        except (ValueError, TypeError):
            return fallback or _BACKOFF_FALLBACK

    if not isinstance(raw, str) or not raw.strip():
        return fallback or _BACKOFF_FALLBACK

    try:
        result = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            match = _TOKEN_RE.fullmatch(token)
            if not match:
                raise ValueError(f"Unparseable token: {token!r}")
            value = int(match.group(1))
            unit = (match.group(2) or "s").lower()
            result.append(value * _UNIT_MAP[unit])
        if not result:
            raise ValueError("Empty schedule")
        return result
    except (ValueError, KeyError):
        logger.warning("Invalid backoff schedule %r, using fallback", raw)
        return fallback or _BACKOFF_FALLBACK


def get_setting(workspace_id, key, workspace_org_id=None):
    """Return the setting value following the cascade:
    workspace override -> org override -> application default.

    Args:
        workspace_id: UUID of the workspace
        key: Setting key (e.g., "approval.internal_reminder_hours")
        workspace_org_id: Optional org ID to avoid an extra query.
                         If not provided, it will be looked up.
    """
    # 1. Check workspace-level override
    try:
        ws_setting = WorkspaceSetting.objects.get(workspace_id=workspace_id, key=key)
        if ws_setting.value is not None:
            return ws_setting.value
    except WorkspaceSetting.DoesNotExist:
        pass

    # 2. Check org-level override
    if workspace_org_id is None:
        from apps.workspaces.models import Workspace

        try:
            workspace_org_id = Workspace.objects.values_list("organization_id", flat=True).get(id=workspace_id)
        except Workspace.DoesNotExist:
            return APP_DEFAULTS.get(key)

    try:
        org_setting = OrgSetting.objects.get(organization_id=workspace_org_id, key=key)
        return org_setting.value
    except OrgSetting.DoesNotExist:
        pass

    # 3. Fall back to application default
    return APP_DEFAULTS.get(key)
