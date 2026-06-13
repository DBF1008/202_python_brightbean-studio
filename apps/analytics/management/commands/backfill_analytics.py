"""Manual analytics backfill — mirrors the existing ``backfill_inbox`` command."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.tasks import (
    backfill_account_analytics,
    sync_all_account_analytics,
)
from apps.settings_manager.defaults import APP_DEFAULTS
from apps.social_accounts.models import AnalyticsPlatformConfig, SocialAccount

# Default ``--days`` lookback when the operator doesn't pass one: the app-level
# ``analytics.optimal_time_lookback_days``. The per-account resolved cap (the
# platform capability, possibly lowered by a workspace/org override) still
# bounds this inside ``backfill_account_analytics``.
_DEFAULT_DAYS = APP_DEFAULTS["analytics.optimal_time_lookback_days"]


class Command(BaseCommand):
    help = "Backfill analytics snapshots for one account or all enabled accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--account-id",
            help="UUID of a single SocialAccount to backfill (default: all enabled).",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=_DEFAULT_DAYS,
            help=f"Lookback window in days (default: {_DEFAULT_DAYS}, capped per-platform).",
        )
        parser.add_argument(
            "--sync-cron",
            action="store_true",
            help="Run the incremental sync cron once instead of a full backfill.",
        )

    def handle(self, *args, **opts):
        if opts["sync_cron"]:
            self.stdout.write("Running sync_all_account_analytics …")
            sync_all_account_analytics()
            self.stdout.write(self.style.SUCCESS("Done."))
            return

        enabled = set(AnalyticsPlatformConfig.enabled_platforms())
        if opts["account_id"]:
            try:
                account = SocialAccount.objects.get(id=opts["account_id"])
            except SocialAccount.DoesNotExist as exc:
                raise CommandError(f"No SocialAccount with id={opts['account_id']!r}") from exc
            if account.platform not in enabled:
                raise CommandError(
                    f"Platform {account.platform!r} is disabled in AnalyticsPlatformConfig — backfill skipped.",
                )
            backfill_account_analytics(str(account.id), days=opts["days"])
            self.stdout.write(self.style.SUCCESS(f"Queued backfill for {account.account_name} ({account.platform})."))
            return

        accounts = list(
            SocialAccount.objects.filter(
                connection_status=SocialAccount.ConnectionStatus.CONNECTED,
                platform__in=enabled,
            )
        )
        for account in accounts:
            backfill_account_analytics(str(account.id), days=opts["days"])
            self.stdout.write(f"  · queued {account.account_name} ({account.platform})")
        self.stdout.write(self.style.SUCCESS(f"Queued {len(accounts)} account(s)."))
