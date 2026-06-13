from django.contrib import admin

from .models import MediaAsset, MediaAssetVersion, MediaFolder


@admin.register(MediaFolder)
class MediaFolderAdmin(admin.ModelAdmin):
    list_display = ("name", "workspace", "parent_folder", "created_at")
    list_filter = ("workspace",)
    search_fields = ("name",)


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = (
        "filename",
        "media_type",
        "workspace",
        "uploaded_by",
        "processing_status",
        "created_at",
    )
    list_filter = ("media_type", "processing_status", "is_starred")
    search_fields = ("filename",)
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(MediaAssetVersion)
class MediaAssetVersionAdmin(admin.ModelAdmin):
    list_display = ("media_asset", "version_number", "change_description", "created_by", "created_at")
    list_filter = ("created_at",)
