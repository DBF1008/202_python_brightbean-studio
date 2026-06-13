"""Application-level default settings.

These are the fallback values when neither workspace nor org overrides exist.
Keys follow a namespaced convention matching the feature spec.
"""

APP_DEFAULTS = {
    # Organization-level defaults
    "org.deletion_grace_period_days": 7,
    "org.deletion_confirmation_link_expiry_hours": 24,
    "org.invitation_expiry_days": 7,
    "org.magic_link_expiry_days": 30,
    "org.session_duration_days": 30,
    "org.login_rate_limit_max_attempts": 5,
    "org.login_rate_limit_lockout_minutes": 15,
    "org.email_batching_delay_minutes": 5,
    "org.2fa_enforcement": False,
    "org.stock_media_attribution": True,
    "org.publish_log_retention_days": 90,
    "org.webhook_delivery_log_retention_days": 30,
    "org.audit_log_retention_days": 365,
    # Workspace-level defaults
    "approval.internal_reminder_hours": 24,
    "approval.client_reminder_hours": 48,
    "approval.max_reminders_per_post": 2,
    "approval.stalled_post_escalation": True,
    "approval.email_subject_template": "{workspace_name} - Posts ready for your review",
    "publishing.first_comment_delay_seconds": 120,
    "publishing.retry_max_attempts": 3,
    "publishing.retry_backoff_schedule": "1min,5min,30min",
    "scheduling.recurring_post_lookahead_days": 90,
    "scheduling.queue_empty_slot_warning_days": 30,
    "inbox.sync_interval_minutes": 5,
    "inbox.auto_resolve_on_reply": True,
    "inbox.sla_target_response_minutes": 120,
    "analytics.optimal_time_lookback_days": 90,
    "analytics.optimal_time_min_posts": 10,
    "analytics.high_frequency_collection_hours": 48,
    "notifications.quiet_hours_start": None,
    "notifications.quiet_hours_end": None,
    "notifications.digest_mode": False,
    "onboarding.client_connection_link_expiry_days": 7,
    # Self-hosted infrastructure defaults
    "infra.account_health_check_hours": 6,
    "infra.token_refresh_check_hours": 1,
    "infra.token_refresh_lookahead_hours": 24,
    "infra.publishing_poll_seconds": 15,
    "infra.media_preprocessing_lookahead_minutes": 60,
    "infra.max_concurrent_publish_jobs": 10,
    "infra.recurrence_generation_interval": "daily",
    "infra.cleanup_job_schedule": "daily_03:00_utc",
}
