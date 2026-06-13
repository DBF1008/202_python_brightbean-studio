"""Models for the Unified Social Inbox (F-3.1)."""

import uuid

from django.conf import settings
from django.db import models

from apps.common.managers import WorkspaceScopedManager


class InboxMessage(models.Model):
    class MessageType(models.TextChoices):
        COMMENT = "comment", "Comment"
        MENTION = "mention", "Mention"
        DM = "dm", "Direct Message"
        REVIEW = "review", "Review"

    class Status(models.TextChoices):
        UNREAD = "unread", "Unread"
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"
        ARCHIVED = "archived", "Archived"

    class Sentiment(models.TextChoices):
        POSITIVE = "positive", "Positive"
        NEUTRAL = "neutral", "Neutral"
        NEGATIVE = "negative", "Negative"

    class SentimentSource(models.TextChoices):
        AUTO = "auto", "Auto"
        MANUAL = "manual", "Manual"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="inbox_messages",
    )
    social_account = models.ForeignKey(
        "social_accounts.SocialAccount",
        on_delete=models.CASCADE,
        related_name="inbox_messages",
    )
    platform_message_id = models.CharField(max_length=255, db_index=True)
    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.COMMENT,
        db_index=True,
    )
    sender_name = models.CharField(max_length=255)
    sender_handle = models.CharField(max_length=255, blank=True, default="")
    sender_avatar_url = models.URLField(max_length=500, blank=True, default="")
    body = models.TextField(blank=True, default="")
    sentiment = models.CharField(
        max_length=10,
        choices=Sentiment.choices,
        default=Sentiment.NEUTRAL,
        db_index=True,
    )
    sentiment_source = models.CharField(
        max_length=10,
        choices=SentimentSource.choices,
        default=SentimentSource.AUTO,
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.UNREAD,
        db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_inbox_messages",
    )
    parent_message = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="thread_replies",
    )
    related_post = models.ForeignKey(
        "composer.PlatformPost",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inbox_messages",
    )
    extra = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "inbox_message"
        ordering = ["-received_at"]
        unique_together = [("social_account", "platform_message_id")]
        indexes = [
            models.Index(
                fields=["workspace", "status", "-received_at"],
                name="inbox_msg_ws_status_recv",
            ),
            models.Index(
                fields=["workspace", "assigned_to", "status"],
                name="inbox_msg_ws_assign_status",
            ),
            models.Index(
                fields=["workspace", "social_account", "-received_at"],
                name="inbox_msg_ws_account_recv",
            ),
        ]

    def __str__(self):
        return f"{self.get_message_type_display()} from {self.sender_name}"

    @property
    def platform(self):
        return self.social_account.platform

    # ------------------------------------------------------------------
    # SLA state helpers
    # ------------------------------------------------------------------

    _ACTIVE_STATUSES = {Status.UNREAD, Status.OPEN}

    @staticmethod
    def compute_sla_fingerprint(status: str, assigned_to_id, config_version: int) -> str:
        """Return a deterministic fingerprint string for the given SLA-relevant state.

        The fingerprint changes whenever:
        * the message status transitions between active (unread/open) and inactive
          (resolved/archived) — covering reopen scenarios;
        * the assignee changes — covering reassignment;
        * the SLA config version bumps — covering target-time or toggle changes.
        """
        active = status in InboxMessage._ACTIVE_STATUSES
        return f"{int(active)}:{assigned_to_id or 'none'}:{config_version}"

    def invalidate_sla_state(self, *, save: bool = True) -> None:
        """Remove the cached ``sla_state`` so that the next ``check_sla()`` run
        re-evaluates this message from scratch.

        Called by views on reopen, reassign, bulk resolve/archive/assign, and
        SLA-config changes so the periodic worker picks up the new state on its
        next cycle.
        """
        if "sla_state" in self.extra:
            del self.extra["sla_state"]
            # Also clean up the legacy one-shot flag if still present.
            self.extra.pop("sla_notified", None)
            if save:
                self.save(update_fields=["extra"])

    def reset_sla_clock(self, *, save: bool = True) -> None:
        """Reset the SLA clock for this message by updating ``received_at`` to now
        and clearing any cached SLA state.

        Used when a message is reopened (transitions from resolved/archived back
        to an active status) so the agent gets a fresh SLA window.
        """
        from django.utils import timezone as _tz

        self.received_at = _tz.now()
        if "sla_state" in self.extra:
            del self.extra["sla_state"]
        self.extra.pop("sla_notified", None)
        if save:
            self.save(update_fields=["extra", "received_at"])

    @classmethod
    def bulk_invalidate_sla_state(cls, queryset) -> int:
        """Strip ``sla_state`` (and legacy ``sla_notified``) from every message
        matched by *queryset* using a single bulk UPDATE where possible.

        Returns the number of rows updated.
        """
        # JSONField bulk key-removal is backend-specific, so we fall back to
        # iterating only the rows that actually carry SLA state.
        affected = queryset.filter(
            models.Q(extra__has_key="sla_state") | models.Q(extra__has_key="sla_notified"),
        )
        count = 0
        for msg in affected.only("id", "extra"):
            changed = False
            if "sla_state" in msg.extra:
                del msg.extra["sla_state"]
                changed = True
            if "sla_notified" in msg.extra:
                del msg.extra["sla_notified"]
                changed = True
            if changed:
                msg.save(update_fields=["extra"])
                count += 1
        return count


class InboxReply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inbox_message = models.ForeignKey(
        InboxMessage,
        on_delete=models.CASCADE,
        related_name="replies",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="inbox_replies",
    )
    body = models.TextField()
    platform_reply_id = models.CharField(max_length=255, blank=True, default="")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inbox_reply"
        ordering = ["sent_at"]

    def __str__(self):
        return f"Reply by {self.author} on {self.sent_at:%Y-%m-%d %H:%M}"


class InternalNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inbox_message = models.ForeignKey(
        InboxMessage,
        on_delete=models.CASCADE,
        related_name="internal_notes",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="inbox_notes",
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "inbox_internal_note"
        ordering = ["created_at"]

    def __str__(self):
        return f"Note by {self.author} on {self.created_at:%Y-%m-%d %H:%M}"


class SavedReply(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="saved_replies",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(
        help_text="Supports variables: {sender_name}, {account_name}, {post_url}",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_saved_replies",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = WorkspaceScopedManager()

    class Meta:
        db_table = "inbox_saved_reply"
        ordering = ["title"]

    def __str__(self):
        return self.title

    def render(self, context: dict) -> str:
        """Substitute variables in body with context values."""
        text = self.body
        for key, value in context.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text


class InboxSLAConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.OneToOneField(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="inbox_sla_config",
    )
    target_response_minutes = models.PositiveIntegerField(default=120)
    is_active = models.BooleanField(default=False)
    auto_resolve_on_reply = models.BooleanField(
        default=True,
        help_text="Automatically mark messages as resolved when a reply is sent.",
    )
    version = models.PositiveIntegerField(
        default=1,
        help_text="Incremented whenever target_response_minutes or is_active changes, "
        "so that check_sla() can detect config updates and re-evaluate overdue notifications.",
    )

    class Meta:
        db_table = "inbox_sla_config"

    def __str__(self):
        return f"SLA Config for {self.workspace} ({self.target_response_minutes}min)"

    def save(self, *args, **kwargs):
        """Bump ``version`` when SLA-relevant fields change.

        We compare against the persisted row (if it exists) so that every
        meaningful update produces a new version, which in turn invalidates
        cached ``sla_state`` fingerprints on InboxMessage.
        """
        if self.pk:
            try:
                old = InboxSLAConfig.objects.get(pk=self.pk)
                if (
                    old.target_response_minutes != self.target_response_minutes
                    or old.is_active != self.is_active
                ):
                    self.version = old.version + 1
            except InboxSLAConfig.DoesNotExist:
                pass
        super().save(*args, **kwargs)
