from django.contrib import admin

from .models import ConnectionLink, ConnectionLinkUsage, OnboardingChecklist


@admin.register(ConnectionLink)
class ConnectionLinkAdmin(admin.ModelAdmin):
    list_display = ("workspace", "created_by", "expires_at", "revoked_at", "created_at")
    list_filter = ("workspace",)
    readonly_fields = ("id", "token", "created_at")
    search_fields = ("workspace__name", "created_by__email")


@admin.register(ConnectionLinkUsage)
class ConnectionLinkUsageAdmin(admin.ModelAdmin):
    list_display = ("connection_link", "social_account", "connected_at")
    readonly_fields = ("id", "connected_at")


@admin.register(OnboardingChecklist)
class OnboardingChecklistAdmin(admin.ModelAdmin):
    list_display = ("user", "workspace", "is_dismissed", "dismissed_at")
    list_filter = ("is_dismissed",)
    readonly_fields = ("id",)
