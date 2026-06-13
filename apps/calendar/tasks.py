"""Background tasks for the Content Calendar (F-2.3)."""

import logging
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.db.models import Q
from django.utils import timezone

from apps.composer.models import PlatformPost, Post, PostMedia

from .models import RecurrenceRule

logger = logging.getLogger(__name__)

LOOKAHEAD_DAYS = 90


def generate_recurring_posts():
    """Generate individual Post records from active RecurrenceRules.

    Runs daily. For each active rule, computes recurrence dates from the
    source post's scheduled_at up to 90 days ahead. Creates clones of the
    source post for each date not yet generated.

    **Dedup strategy (idempotent):**
    A generated recurrence carries a stable ``recurrence_source`` FK back
    to the originating post.  Dedup therefore uses
    ``(recurrence_source=<source>, scheduled_at__date)`` — immune to
    same-caption collisions across different posts and to caption edits
    on the source.  For backwards compatibility with recurrences that
    were generated before the field existed, a secondary check matches
    legacy posts that have the same workspace, caption, and date but no
    ``recurrence_source``.
    """
    rules = RecurrenceRule.objects.filter(is_active=True).select_related("post")
    now = timezone.now()
    cutoff = now.date() + timedelta(days=LOOKAHEAD_DAYS)
    generated_total = 0

    for rule in rules:
        source = rule.post
        if not source.scheduled_at:
            continue

        # Respect end_date
        end = rule.end_date or cutoff
        if end > cutoff:
            end = cutoff

        # Compute recurrence dates
        base_date = source.scheduled_at.date()
        base_time = source.scheduled_at.time()
        base_tz = source.scheduled_at.tzinfo

        dates = _compute_recurrence_dates(base_date, rule.frequency, rule.interval, end)

        if not dates:
            rule.last_generated_at = now
            rule.save(update_fields=["last_generated_at"])
            continue

        # ----------------------------------------------------------
        # Idempotent dedup
        # ----------------------------------------------------------
        # Primary: match on stable recurrence_source FK.  This is
        # immune to caption changes and same-caption collisions.
        #
        # Fallback: for legacy posts generated before the
        # recurrence_source field existed (recurrence_source IS NULL),
        # match by workspace + caption + date so we don't regenerate
        # them.  Posts that genuinely have no recurrence relationship
        # are excluded by requiring recurrence_source IS NULL *and*
        # the same caption.
        # ----------------------------------------------------------
        existing_dates = set(
            Post.objects.filter(
                Q(recurrence_source=source)
                | Q(
                    recurrence_source__isnull=True,
                    workspace=source.workspace,
                    caption=source.caption,
                ),
                scheduled_at__date__in=dates,
            )
            .exclude(pk=source.pk)
            .values_list("scheduled_at__date", flat=True)
        )

        for d in dates:
            if d in existing_dates or d <= now.date():
                continue

            from datetime import datetime

            scheduled_dt = datetime.combine(d, base_time)
            if base_tz:
                scheduled_dt = scheduled_dt.replace(tzinfo=base_tz)

            # Clone the post — recurrence_source stamps the lineage
            new_post = Post.objects.create(
                workspace=source.workspace,
                author=source.author,
                title=source.title,
                caption=source.caption,
                first_comment=source.first_comment,
                internal_notes=source.internal_notes,
                tags=source.tags,
                category=source.category,
                scheduled_at=scheduled_dt,
                recurrence_source=source,
            )

            # Clone platform posts in bulk, preserving per-platform offsets
            source_pps = list(source.platform_posts.all())
            if source_pps:
                new_pps = []
                for pp in source_pps:
                    # Preserve the offset between source PP's scheduled_at and
                    # source post's scheduled_at, so per-platform time deltas
                    # carry into each recurrence.
                    pp_scheduled = None
                    if pp.scheduled_at and source.scheduled_at:
                        delta = pp.scheduled_at - source.scheduled_at
                        pp_scheduled = scheduled_dt + delta
                    new_pps.append(
                        PlatformPost(
                            post=new_post,
                            social_account=pp.social_account,
                            platform_specific_title=pp.platform_specific_title,
                            platform_specific_caption=pp.platform_specific_caption,
                            platform_specific_first_comment=pp.platform_specific_first_comment,
                            platform_specific_media=pp.platform_specific_media,
                            platform_extra=pp.platform_extra,
                            scheduled_at=pp_scheduled,
                            status="scheduled",
                        )
                    )
                PlatformPost.objects.bulk_create(new_pps)

                # Sync Post.scheduled_at to min of children.
                from apps.composer.services import sync_post_scheduled_at

                sync_post_scheduled_at(new_post)

            # Clone media attachments in bulk
            source_media = list(source.media_attachments.all())
            if source_media:
                PostMedia.objects.bulk_create(
                    [
                        PostMedia(
                            post=new_post,
                            media_asset=pm.media_asset,
                            position=pm.position,
                            alt_text=pm.alt_text,
                            platform_overrides=pm.platform_overrides,
                        )
                        for pm in source_media
                    ]
                )

            generated_total += 1

        rule.last_generated_at = now
        rule.save(update_fields=["last_generated_at"])

    logger.info("Generated %d recurring posts.", generated_total)
    return generated_total


def _compute_recurrence_dates(base_date, frequency, interval, end_date):
    """Compute a list of recurrence dates from base_date to end_date."""
    dates = []
    current = base_date

    max_recurrences = LOOKAHEAD_DAYS * 2  # Safety limit
    for _ in range(max_recurrences):
        if frequency == "daily":
            current = current + timedelta(days=interval)
        elif frequency == "weekly":
            current = current + timedelta(weeks=interval)
        elif frequency == "monthly":
            current = current + relativedelta(months=interval)
        else:
            break

        if current > end_date:
            break

        dates.append(current)

    return dates
