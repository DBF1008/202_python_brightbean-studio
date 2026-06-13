from django.contrib import admin

from .models import Workspace


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_archived", "created_at")
    list_filter = ("is_archived", "approval_workflow_mode")
    search_fields = ("name",)
