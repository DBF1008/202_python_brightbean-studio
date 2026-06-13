"""Management command to run the inbox sync worker."""

import signal
import time

from django.core.management.base import BaseCommand

from apps.inbox.tasks import InboxSyncEngine


class Command(BaseCommand):
    help = "Run the inbox sync worker that polls for new messages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--interval",
            type=int,
            default=300,
            help="Poll interval in seconds (default: 300).",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run sync once and exit.",
        )

    def handle(self, *args, **options):
        interval = options["interval"]
        once = options["once"]
        engine = InboxSyncEngine()

        running = True

        def stop_handler(signum, frame):
            nonlocal running
            running = False
            self.stdout.write("Shutting down inbox sync worker...")

        signal.signal(signal.SIGINT, stop_handler)
        signal.signal(signal.SIGTERM, stop_handler)

        self.stdout.write(self.style.SUCCESS("Inbox sync worker started."))

        while running:
            engine.sync_all()
            engine.check_sla()

            if once:
                break

            time.sleep(interval)

        self.stdout.write("Inbox sync worker stopped.")
