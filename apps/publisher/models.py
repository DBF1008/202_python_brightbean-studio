"""Publishing Engine models (F-2.4) - publish logs and rate limiting."""

import uuid

from django.db import models


class PublishLog(models.Model):
    """Log entry for every publish attempt (including retries).

    Retained for 90 days, then cleaned up by a background job.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    platform_post = models.ForeignKey(
        "composer.PlatformPost",
        on_delete=models.CASCADE,
        related_name="publish_logs",
    )
    attempt_number = models.PositiveIntegerField(default=1)
    status_code = models.IntegerField(null=True, blank=True, help_text="HTTP status from platform API.")
    response_body = models.TextField(
        blank=True,
        default="",
        help_text="Truncated response body (max 1000 chars).",
    )
    error_message = models.TextField(blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0, help_text="Request duration in milliseconds.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "publisher_publish_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["platform_post", "-created_at"], name="idx_publog_pp_created"),
        ]

    def __str__(self):
        return f"PublishLog(attempt={self.attempt_number}, status={self.status_code})"


class RateLimitState(models.Model):
    """Track API rate limit state per social account per platform.

    Updated from API response headers after each call.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    social_account = models.ForeignKey(
        "social_accounts.SocialAccount",
        on_delete=models.CASCADE,
        related_name="rate_limit_states",
    )
    platform = models.CharField(max_length=30)
    requests_remaining = models.IntegerField(default=-1, help_text="-1 means unknown.")
    window_resets_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the rate limit window resets.",
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publisher_rate_limit_state"
        unique_together = [("social_account", "platform")]

    def __str__(self):
        return f"RateLimitState({self.platform}): {self.requests_remaining} remaining"

    @property
    def is_rate_limited(self):
        """Check if we're currently rate-limited."""
        from django.utils import timezone

        if self.requests_remaining == 0 and self.window_resets_at:
            return timezone.now() < self.window_resets_at
        return False

    @property
    def can_publish(self):
        """Check if there's headroom for a publish attempt."""
        if self.requests_remaining == -1:
            return True  # Unknown - try anyway
        if self.requests_remaining > 0:
            return True
        return not self.is_rate_limited
