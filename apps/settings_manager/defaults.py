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
    # ── Analytics: sync cadence & backfill ────────────────────────────
    #
    # Post-sync cadence ladder.  Each entry is ``[max_age_days, interval_hours]``;
    # the first row whose ``max_age_days`` exceeds the post's age wins.  Posts
    # older than the *last* row's ``max_age_days`` are no longer synced.
    # The values below reproduce the original hardcoded schedule:
    #   <24 h → 1 h,  1–7 d → 6 h,  7–30 d → 1 d,  30–90 d → 7 d,  >90 d → stop
    "analytics.post_sync_cadence": [[1, 1], [7, 6], [30, 24], [90, 168]],
    # How often account-level metrics are synced (hours).  The hourly cron
    # skips accounts that already have today's row, so this effectively
    # caps account syncs to once per this many hours.
    "analytics.account_sync_interval_hours": 24,
    # Sentinel delay (minutes) for just-connected accounts / just-published
    # posts with no snapshot rows yet — the agent polls back shortly rather
    # than waiting a full sync interval.
    "analytics.first_poll_delay_minutes": 5,
    # Default backfill window (days) on initial connect / reconnect.
    "analytics.backfill_days_default": 90,
    # Per-platform backfill overrides.  ``0`` means the platform has no
    # analytics surface and the backfill task should skip it entirely.
    "analytics.backfill_days_per_platform": {
        "facebook": 90,
        "instagram": 90,
        "instagram_login": 90,
        "linkedin_company": 90,
        "youtube": 90,
        "pinterest": 90,
        "threads": 90,
        "google_business": 90,
        "tiktok": 60,
        "bluesky": 0,
        "mastodon": 0,
        "linkedin_personal": 0,
    },
    # Number of recent days to walk back when syncing account-level metrics.
    # Some providers (YouTube Analytics) lag 1-2 days; iterating recent days
    # lets finalized data backfill into past dates instead of being lost.
    "analytics.account_metrics_recent_days": 3,
    # ── Analytics: optimal-time & high-frequency collection ──────────
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
