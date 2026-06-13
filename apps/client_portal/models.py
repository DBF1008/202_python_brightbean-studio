"""Client Portal models (F-1.4).

Models:
    MagicLinkToken - Time-limited token for passwordless client access.
"""

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


def _generate_magic_token():
    return secrets.token_urlsafe(48)


def _default_expiry():
    return timezone.now() + timedelta(days=30)


class MagicLinkToken(models.Model):
    """A magic link token for passwordless client portal access."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="magic_link_tokens",
    )
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="magic_link_tokens",
    )
    token = models.CharField(
        max_length=128,
        unique=True,
        db_index=True,
        default=_generate_magic_token,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_expiry)
    last_used_at = models.DateTimeField(null=True, blank=True)
    is_consumed = models.BooleanField(default=False)

    class Meta:
        db_table = "client_portal_magic_link_token"
        indexes = [
            models.Index(fields=["user", "workspace"], name="idx_magic_user_ws"),
        ]

    def __str__(self):
        return f"MagicLink for {self.user} → {self.workspace}"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_expired
