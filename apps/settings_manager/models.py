import uuid

from django.db import models

from apps.common.managers import OrgScopedManager


class OrgSetting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="settings",
    )
    key = models.CharField(max_length=255)
    value = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    objects = OrgScopedManager()

    class Meta:
        db_table = "settings_org_setting"
        unique_together = [("organization", "key")]

    def __str__(self):
        return f"{self.organization.name}: {self.key}"


class WorkspaceSetting(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="settings",
    )
    key = models.CharField(max_length=255)
    value = models.JSONField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "settings_workspace_setting"
        unique_together = [("workspace", "key")]

    def __str__(self):
        return f"{self.workspace.name}: {self.key}"
