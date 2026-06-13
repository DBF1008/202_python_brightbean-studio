from django.contrib import admin

from .models import Organization


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "default_timezone", "created_at", "is_deletion_pending")
    search_fields = ("name",)
    readonly_fields = ("id", "created_at", "updated_at")
