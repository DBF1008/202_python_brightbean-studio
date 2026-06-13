"""Background tasks for the notification system.

These are meant to be called by django-background-tasks or a cron schedule.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)


def send_daily_digests():
    """Send daily email digests to users who have digest mode enabled.

    Should be scheduled to run once daily (e.g., 08:00 in each user's timezone).
    """
    from .models import Notification, QuietHours

    digest_users = QuietHours.objects.filter(digest_mode=True).select_related("user")

    for qh in digest_users:
        user = qh.user
        if not user.is_active:
            continue

        since = timezone.now() - timedelta(hours=24)
        notifications = list(
            Notification.objects.filter(
                user=user,
                created_at__gte=since,
            ).order_by("-created_at")[:50]
        )

        if not notifications:
            continue

        context = {
            "notifications": notifications,
            "user": user,
            "date": timezone.now(),
            "app_url": getattr(settings, "APP_URL", "http://localhost:8000"),
        }

        try:
            text_content = render_to_string("notifications/email/digest.txt", context)
            html_content = render_to_string("notifications/email/digest.html", context)

            msg = EmailMultiAlternatives(
                subject=f"Daily Digest - {len(notifications)} notification{'s' if len(notifications) != 1 else ''}",
                body=text_content,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@localhost"),
                to=[user.email],
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)

            logger.info("Sent daily digest to %s (%d notifications)", user.email, len(notifications))
        except Exception:
            logger.exception("Failed to send daily digest to %s", user.email)


def retry_failed_deliveries():
    """Retry pending notification deliveries that are past their backoff window.

    Should be scheduled to run every minute.
    """
    from .engine import retry_failed_deliveries as _retry

    count = _retry()
    if count > 0:
        logger.info("Retried %d failed notification deliveries", count)
