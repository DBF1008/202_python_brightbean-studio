"""Management command to detect and remove orphaned media assets.

Orphaned assets are MediaAsset records (and their R2/S3 files) that are not
referenced by any post, idea, platform post, or template.  They accumulate
when users upload files in the composer but never save a post, or when posts
are deleted without cleaning up the underlying assets.

Usage:
    python manage.py cleanup_orphaned_media --once --dry-run
    python manage.py cleanup_orphaned_media --once --min-age-days 7
    python manage.py cleanup_orphaned_media          # continuous, every 24h
"""

import signal
import time
import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from apps.media_library.models import MediaAsset
from apps.media_library.services import ProtectedAssetError, delete_asset


class Command(BaseCommand):
    help = "Detect and remove orphaned media assets not referenced by any post, idea, or template."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report orphaned assets without deleting them.",
        )
        parser.add_argument(
            "--min-age-days",
            type=int,
            default=14,
            help="Only consider assets older than N days (default: 14, matches SESSION_COOKIE_AGE).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Process deletions in batches of N (default: 100).",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run a single cleanup cycle and exit.",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=86400,
            help="Seconds between runs in continuous mode (default: 86400 = 24h).",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        min_age_days = options["min_age_days"]
        batch_size = options["batch_size"]
        run_once = options["once"]
        interval = options["interval"]

        self.running = True

        def signal_handler(signum, frame):
            self.stdout.write(self.style.WARNING("\nShutting down cleanup..."))
            self.running = False

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        if dry_run:
            self.stdout.write(self.style.WARNING("[cleanup] DRY RUN mode - no deletions will be performed"))

        while self.running:
            self._run_cleanup(dry_run, min_age_days, batch_size)
            if run_once:
                break
            self.stdout.write(f"[cleanup] Next run in {interval}s...")
            time.sleep(interval)

    def _run_cleanup(self, dry_run, min_age_days, batch_size):
        cutoff = timezone.now() - timedelta(days=min_age_days)
        self.stdout.write(
            f"[cleanup] Scanning assets older than {min_age_days} days (cutoff: {cutoff.strftime('%Y-%m-%d %H:%M')})"
        )

        # Phase 1: Collect FK-referenced asset IDs
        fk_referenced = self._get_fk_referenced_ids()
        self.stdout.write(f"[cleanup] FK-referenced assets: {len(fk_referenced)}")

        # Phase 2: Collect JSON-referenced asset IDs
        json_referenced = self._get_json_referenced_ids()
        self.stdout.write(f"[cleanup] JSON-referenced assets: {len(json_referenced)}")

        all_referenced = fk_referenced | json_referenced

        # Phase 3: Query orphaned assets
        orphaned_qs = MediaAsset.objects.filter(created_at__lt=cutoff).exclude(id__in=all_referenced)
        orphaned_ids = list(orphaned_qs.values_list("id", flat=True))
        total_count = len(orphaned_ids)

        if total_count == 0:
            self.stdout.write(self.style.SUCCESS("[cleanup] No orphaned assets found."))
            return

        # Calculate total size
        total_bytes = orphaned_qs.aggregate(total=__import__("django").db.models.Sum("file_size"))["total"] or 0
        total_mb = total_bytes / (1024 * 1024)

        self.stdout.write(f"[cleanup] Orphaned candidates: {total_count} (~{total_mb:.1f} MB)")

        if dry_run:
            # Show details for up to 50 assets
            sample = MediaAsset.objects.filter(id__in=orphaned_ids[:50])
            for asset in sample:
                self.stdout.write(
                    f"[cleanup]   Would delete: {asset.id} "
                    f"({asset.filename}, {asset.media_type}, "
                    f"{asset.file_size / (1024 * 1024):.1f} MB, "
                    f"created {asset.created_at.strftime('%Y-%m-%d')})"
                )
            if total_count > 50:
                self.stdout.write(f"[cleanup]   ... and {total_count - 50} more")
            self.stdout.write(
                self.style.WARNING(
                    f"[cleanup] DRY RUN complete: {total_count} assets (~{total_mb:.1f} MB) would be deleted"
                )
            )
            return

        # Delete in batches
        deleted = 0
        skipped = 0
        errors = 0

        for i in range(0, total_count, batch_size):
            if not self.running:
                self.stdout.write(self.style.WARNING("[cleanup] Interrupted, stopping..."))
                break

            batch_ids = orphaned_ids[i : i + batch_size]
            batch = MediaAsset.objects.filter(id__in=batch_ids)

            for asset in batch:
                if not self.running:
                    break
                try:
                    asset_info = f"{asset.id} ({asset.filename})"
                    delete_asset(asset)
                    deleted += 1
                    self.stdout.write(f"[cleanup] Deleted: {asset_info}")
                except ProtectedAssetError:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"[cleanup] Skipped (protected): {asset.id}"))
                except Exception as e:
                    errors += 1
                    self.stdout.write(self.style.ERROR(f"[cleanup] Error deleting {asset.id}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"[cleanup] Complete: {deleted} deleted, {skipped} skipped, {errors} errors "
                f"(out of {total_count} orphaned)"
            )
        )

    def _get_fk_referenced_ids(self):
        """Collect all asset IDs referenced via foreign keys."""
        from apps.composer.models import Idea, IdeaMedia, PostMedia

        referenced = set()
        referenced.update(PostMedia.objects.values_list("media_asset_id", flat=True))
        referenced.update(IdeaMedia.objects.values_list("media_asset_id", flat=True))
        referenced.update(Idea.objects.filter(media_asset__isnull=False).values_list("media_asset_id", flat=True))
        return referenced

    def _get_json_referenced_ids(self):
        """Collect all asset IDs embedded in JSON fields."""
        if connection.vendor == "postgresql":
            return self._get_json_referenced_ids_postgres()
        return self._get_json_referenced_ids_python()

    def _get_json_referenced_ids_postgres(self):
        """Extract asset IDs from JSON fields using PostgreSQL jsonb functions."""
        referenced = set()

        with connection.cursor() as cursor:
            # PlatformPost.platform_extra -> thumbnail_asset_id
            cursor.execute("""
                SELECT DISTINCT platform_extra->>'thumbnail_asset_id'
                FROM composer_platform_post
                WHERE platform_extra IS NOT NULL
                  AND platform_extra->>'thumbnail_asset_id' IS NOT NULL
            """)
            for (val,) in cursor.fetchall():
                referenced.add(self._to_uuid(val))

            # PlatformPost.platform_extra -> cover_image_asset_id
            cursor.execute("""
                SELECT DISTINCT platform_extra->>'cover_image_asset_id'
                FROM composer_platform_post
                WHERE platform_extra IS NOT NULL
                  AND platform_extra->>'cover_image_asset_id' IS NOT NULL
            """)
            for (val,) in cursor.fetchall():
                referenced.add(self._to_uuid(val))

            # PlatformPost.platform_specific_media (JSON array of IDs)
            cursor.execute("""
                SELECT DISTINCT elem::text
                FROM composer_platform_post,
                     jsonb_array_elements_text(platform_specific_media) AS elem
                WHERE platform_specific_media IS NOT NULL
                  AND jsonb_typeof(platform_specific_media) = 'array'
            """)
            for (val,) in cursor.fetchall():
                referenced.add(self._to_uuid(val))

            # PostTemplate.template_data -> media_asset_ids (JSON array)
            cursor.execute("""
                SELECT DISTINCT elem::text
                FROM composer_post_template,
                     jsonb_array_elements_text(template_data->'media_asset_ids') AS elem
                WHERE template_data IS NOT NULL
                  AND template_data ? 'media_asset_ids'
                  AND jsonb_typeof(template_data->'media_asset_ids') = 'array'
            """)
            for (val,) in cursor.fetchall():
                referenced.add(self._to_uuid(val))

        referenced.discard(None)
        return referenced

    def _get_json_referenced_ids_python(self):
        """Extract asset IDs from JSON fields by iterating in Python (SQLite fallback)."""
        from apps.composer.models import PlatformPost, PostTemplate

        referenced = set()

        for pp in PlatformPost.objects.exclude(platform_extra=None).only("platform_extra"):
            extra = pp.platform_extra or {}
            if extra.get("thumbnail_asset_id"):
                referenced.add(self._to_uuid(extra["thumbnail_asset_id"]))
            if extra.get("cover_image_asset_id"):
                referenced.add(self._to_uuid(extra["cover_image_asset_id"]))

        for pp in PlatformPost.objects.exclude(platform_specific_media=None).only("platform_specific_media"):
            if isinstance(pp.platform_specific_media, list):
                for val in pp.platform_specific_media:
                    referenced.add(self._to_uuid(val))

        for tmpl in PostTemplate.objects.exclude(template_data=None).only("template_data"):
            data = tmpl.template_data or {}
            for val in data.get("media_asset_ids", []):
                referenced.add(self._to_uuid(val))

        referenced.discard(None)
        return referenced

    def _to_uuid(self, val):
        """Safely convert a string to UUID, returning None on failure."""
        if not val:
            return None
        try:
            return uuid.UUID(str(val))
        except (ValueError, AttributeError):
            return None
