"""URL patterns for the Unified Social Inbox."""

from django.urls import path

from . import views

app_name = "inbox"

urlpatterns = [
    # Main inbox feed
    path("", views.inbox_feed, name="feed"),
    # Message detail + thread
    path("<uuid:message_id>/", views.message_detail, name="message_detail"),
    # Reply to message
    path("<uuid:message_id>/reply/", views.send_reply, name="send_reply"),
    # Internal notes
    path("<uuid:message_id>/note/", views.add_note, name="add_note"),
    # Assignment
    path("<uuid:message_id>/assign/", views.assign_message, name="assign"),
    # Status changes
    path("<uuid:message_id>/status/", views.change_status, name="change_status"),
    # Sentiment override
    path("<uuid:message_id>/sentiment/", views.change_sentiment, name="change_sentiment"),
    # Bulk actions
    path("bulk-action/", views.bulk_action, name="bulk_action"),
    # Saved replies
    path("saved-replies/", views.saved_replies_list, name="saved_replies"),
    path("saved-replies/create/", views.saved_reply_create, name="saved_reply_create"),
    path("saved-replies/<uuid:reply_id>/edit/", views.saved_reply_edit, name="saved_reply_edit"),
    path("saved-replies/<uuid:reply_id>/delete/", views.saved_reply_delete, name="saved_reply_delete"),
    # SLA config
    path("sla-config/", views.sla_config, name="sla_config"),
]
