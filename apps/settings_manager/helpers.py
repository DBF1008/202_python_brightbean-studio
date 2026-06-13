"""Settings cascade helper: workspace -> org -> app default."""

from .defaults import APP_DEFAULTS
from .models import OrgSetting, WorkspaceSetting


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
