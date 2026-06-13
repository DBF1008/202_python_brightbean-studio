from django.contrib import admin

from .models import ApprovalAction, ApprovalReminder, PostComment


@admin.register(ApprovalAction)
class ApprovalActionAdmin(admin.ModelAdmin):
    list_display = ("post", "user", "action", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("post__caption", "user__email")
    readonly_fields = ("id", "created_at")


@admin.register(PostComment)
class PostCommentAdmin(admin.ModelAdmin):
    list_display = ("post", "author", "visibility", "created_at", "deleted_at")
    list_filter = ("visibility", "created_at")
    search_fields = ("body", "author__email")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(ApprovalReminder)
class ApprovalReminderAdmin(admin.ModelAdmin):
    list_display = ("post", "stage", "reminder_count", "last_reminder_at", "escalated")
    list_filter = ("stage", "escalated")
    readonly_fields = ("id",)
