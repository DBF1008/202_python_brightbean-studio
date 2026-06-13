"""Management command to run approval reminder checks.

Usage:
    python manage.py run_approval_reminders

This runs the reminder check once. Schedule it via cron or process_tasks
for periodic execution (recommended: every hour).
"""

from django.core.management.base import BaseCommand

from apps.approvals.tasks import check_approval_reminders


class Command(BaseCommand):
    help = "Check for stalled approvals and send reminder notifications."

    def handle(self, *args, **options):
        self.stdout.write("Checking approval reminders...")
        check_approval_reminders()
        self.stdout.write(self.style.SUCCESS("Done."))
