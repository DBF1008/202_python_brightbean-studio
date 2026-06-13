from django.contrib import admin

from .models import MagicLinkToken


@admin.register(MagicLinkToken)
class MagicLinkTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "workspace", "created_at", "expires_at", "is_consumed")
    list_filter = ("is_consumed", "created_at")
    search_fields = ("user__email", "workspace__name")
    readonly_fields = ("id", "token", "created_at")
