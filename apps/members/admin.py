from django.contrib import admin

from .models import CustomRole, Invitation, OrgMembership, WorkspaceMembership


@admin.register(OrgMembership)
class OrgMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "org_role", "invited_at", "accepted_at")
    list_filter = ("org_role",)
    search_fields = ("user__email",)


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "workspace", "workspace_role", "custom_role", "added_at")
    list_filter = ("workspace_role",)
    search_fields = ("user__email",)


@admin.register(CustomRole)
class CustomRoleAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "created_at")
    search_fields = ("name",)


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ("email", "organization", "invited_by", "expires_at", "accepted_at")
    list_filter = ("accepted_at",)
    search_fields = ("email",)
