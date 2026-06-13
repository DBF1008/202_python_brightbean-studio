"""Org-scoped and workspace-scoped model managers that auto-filter queries."""

from django.db import models


class OrgScopedManager(models.Manager):
    """Manager that auto-filters queries by organization_id.

    Usage in views/middleware: set the organization on the manager
    before querying:
        MyModel.objects.for_org(org_id).all()
    """

    def for_org(self, organization_id):
        return self.get_queryset().filter(organization_id=organization_id)


class WorkspaceScopedManager(models.Manager):
    """Manager that auto-filters queries by workspace_id.

    Usage:
        MyModel.objects.for_workspace(workspace_id).all()
    """

    def for_workspace(self, workspace_id):
        return self.get_queryset().filter(workspace_id=workspace_id)


class OrgScopedModel(models.Model):
    """Abstract model that includes organization FK and scoped manager."""

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    objects = OrgScopedManager()

    class Meta:
        abstract = True


class WorkspaceScopedModel(models.Model):
    """Abstract model that includes workspace FK and scoped manager."""

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="%(class)ss",
    )

    objects = WorkspaceScopedManager()

    class Meta:
        abstract = True
