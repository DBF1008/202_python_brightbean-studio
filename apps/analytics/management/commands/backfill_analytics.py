"""Manual analytics backfill — mirrors the existing ``backfill_inbox`` command."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.analytics.analytics_config import resolve_analytics_config
from apps.analytics.tasks import (
    DEFAULT_BACKFILL_DAYS,
    backfill_account_analytics,
    sync_all_account_analytics,
)
from apps.social_accounts.models import AnalyticsPlatformConfig, SocialAccount


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
            default=None,
            help=(
                "Lookback window in days.  Defaults to the per-workspace "
                "``analytics.backfill_days_default`` setting (app default: "
                f"{DEFAULT_BACKFILL_DAYS}), capped per-platform by the "
                "``analytics.backfill_days_per_platform`` cascade."
            ),
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
                account = SocialAccount.objects.select_related("workspace").get(id=opts["account_id"])
            except SocialAccount.DoesNotExist as exc:
                raise CommandError(f"No SocialAccount with id={opts['account_id']!r}") from exc
            if account.platform not in enabled:
                raise CommandError(
                    f"Platform {account.platform!r} is disabled in AnalyticsPlatformConfig — backfill skipped.",
                )
            cfg = resolve_analytics_config(account.workspace_id, account.workspace.organization_id)
            days = opts["days"] if opts["days"] is not None else cfg.backfill_days_default
            backfill_account_analytics(str(account.id), days=days)
            cap = cfg.backfill_cap_for(account.platform)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Queued backfill for {account.account_name} ({account.platform}): "
                    f"requested {days}d, platform cap {cap}d."
                )
            )
            return

        accounts = list(
            SocialAccount.objects.filter(
                connection_status=SocialAccount.ConnectionStatus.CONNECTED,
                platform__in=enabled,
            ).select_related("workspace")
        )
        for account in accounts:
            days = opts["days"]  # None → task resolves per-workspace default
            backfill_account_analytics(str(account.id), days=days)
            self.stdout.write(f"  · queued {account.account_name} ({account.platform})")
        self.stdout.write(self.style.SUCCESS(f"Queued {len(accounts)} account(s)."))
