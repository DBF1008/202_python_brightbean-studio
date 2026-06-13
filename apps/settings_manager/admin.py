from django.contrib import admin

from .models import OrgSetting, WorkspaceSetting


@admin.register(OrgSetting)
class OrgSettingAdmin(admin.ModelAdmin):
    list_display = ("organization", "key", "value", "updated_at")
    list_filter = ("organization",)
    search_fields = ("key",)


@admin.register(WorkspaceSetting)
class WorkspaceSettingAdmin(admin.ModelAdmin):
    list_display = ("workspace", "key", "value", "updated_at")
    list_filter = ("workspace",)
    search_fields = ("key",)
