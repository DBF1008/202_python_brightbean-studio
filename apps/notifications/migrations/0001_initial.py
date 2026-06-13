import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("post_submitted", "Post submitted for approval"),
                            ("post_approved", "Post approved"),
                            ("post_changes_requested", "Post changes requested"),
                            ("post_rejected", "Post rejected"),
                            ("post_published", "Post published"),
                            ("post_failed", "Post failed"),
                            ("new_inbox_message", "New inbox message"),
                            ("inbox_sla_overdue", "Inbox SLA overdue"),
                            ("client_approval_requested", "Client approval requested"),
                            ("team_member_invited", "Team member invited"),
                            ("social_account_disconnected", "Social account disconnected"),
                            ("report_generated", "Report generated"),
                            ("engagement_alert", "Engagement alert"),
                        ],
                        db_index=True,
                        max_length=50,
                    ),
                ),
                ("title", models.CharField(max_length=255)),
                ("body", models.TextField(blank=True, default="")),
                ("data", models.JSONField(blank=True, default=dict)),
                ("is_read", models.BooleanField(db_index=True, default=False)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "notifications_notification",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "-created_at"], name="notificatio_user_id_created_idx"),
        ),
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "is_read", "-created_at"], name="notificatio_user_id_is_read_idx"),
        ),
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "event_type",
                    models.CharField(
                        choices=[
                            ("post_submitted", "Post submitted for approval"),
                            ("post_approved", "Post approved"),
                            ("post_changes_requested", "Post changes requested"),
                            ("post_rejected", "Post rejected"),
                            ("post_published", "Post published"),
                            ("post_failed", "Post failed"),
                            ("new_inbox_message", "New inbox message"),
                            ("inbox_sla_overdue", "Inbox SLA overdue"),
                            ("client_approval_requested", "Client approval requested"),
                            ("team_member_invited", "Team member invited"),
                            ("social_account_disconnected", "Social account disconnected"),
                            ("report_generated", "Report generated"),
                            ("engagement_alert", "Engagement alert"),
                        ],
                        max_length=50,
                    ),
                ),
                (
                    "channel",
                    models.CharField(
                        choices=[("in_app", "In-App"), ("email", "Email"), ("webhook", "Webhook")], max_length=20
                    ),
                ),
                ("is_enabled", models.BooleanField(default=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "notifications_preference",
                "unique_together": {("user", "event_type", "channel")},
            },
        ),
        migrations.CreateModel(
            name="NotificationDelivery",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "channel",
                    models.CharField(
                        choices=[("in_app", "In-App"), ("email", "Email"), ("webhook", "Webhook")], max_length=20
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("delivered", "Delivered"), ("failed", "Failed")],
                        db_index=True,
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("error_message", models.TextField(blank=True, default="")),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("next_retry_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "notification",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="deliveries",
                        to="notifications.notification",
                    ),
                ),
            ],
            options={
                "db_table": "notifications_delivery",
            },
        ),
        migrations.AddIndex(
            model_name="notificationdelivery",
            index=models.Index(fields=["status", "next_retry_at"], name="notificatio_status_next_retry_idx"),
        ),
        migrations.CreateModel(
            name="QuietHours",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("is_enabled", models.BooleanField(default=False)),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("end_time", models.TimeField(blank=True, null=True)),
                ("timezone", models.CharField(default="UTC", max_length=50)),
                (
                    "digest_mode",
                    models.BooleanField(default=False, help_text="Batch email notifications into a daily digest."),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="quiet_hours",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "notifications_quiet_hours",
                "verbose_name_plural": "Quiet hours",
            },
        ),
    ]
