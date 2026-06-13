from django.urls import path

from . import views

app_name = "media_library"

urlpatterns = [
    path("", views.library_index, name="index"),
    path("upload/", views.upload, name="upload"),
    path("search/", views.search, name="search"),
    # Folders
    path("folders/create/", views.folder_create, name="folder_create"),
    path("folders/<uuid:folder_id>/rename/", views.folder_rename, name="folder_rename"),
    path("folders/<uuid:folder_id>/delete/", views.folder_delete, name="folder_delete"),
    # Tags
    path("tags/autocomplete/", views.tag_autocomplete, name="tag_autocomplete"),
    # Assets
    path("<uuid:asset_id>/", views.asset_detail, name="asset_detail"),
    path("<uuid:asset_id>/edit/", views.asset_edit, name="asset_edit"),
    path("<uuid:asset_id>/star/", views.asset_star_toggle, name="asset_star"),
    path("<uuid:asset_id>/tags/", views.asset_update_tags, name="asset_tags"),
    path("<uuid:asset_id>/move/", views.asset_move, name="asset_move"),
    path("<uuid:asset_id>/delete/", views.asset_delete, name="asset_delete"),
    path("<uuid:asset_id>/download/", views.asset_download, name="asset_download"),
    path("<uuid:asset_id>/versions/", views.version_list, name="version_list"),
    path("<uuid:asset_id>/versions/<uuid:version_id>/restore/", views.version_restore, name="version_restore"),
    path("<uuid:asset_id>/processing-status/", views.processing_status, name="processing_status"),
]
