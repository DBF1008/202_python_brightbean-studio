"""Background tasks for the Content Calendar (F-2.3)."""

import logging
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.composer.models import PlatformPost, Post, PostMedia
from apps.composer.services import sync_post_scheduled_at

from .models import RecurrenceRule

logger = logging.getLogger(__name__)

LOOKAHEAD_DAYS = 90


def generate_recurring_posts():
    """Generate individual Post records from active RecurrenceRules.

    Runs daily. For each active rule, computes recurrence dates from the
    source post's scheduled_at up to 90 days ahead and creates a clone of the
    source post for every occurrence not yet generated.

    Idempotency is anchored on the stable ``(recurrence_source, recurrence_date)``
    lineage stored on each generated post rather than on its mutable content.
    This means the task is safe to re-run, and editing the source post's
    caption, category, or attachments never causes a missed, duplicated, or
    falsely-skipped occurrence. A partial unique constraint on those two
    columns backs this up at the database level, so even concurrent runs
    cannot double-create the same occurrence.
    """
    rules = RecurrenceRule.objects.filter(is_active=True).select_related("post")
    now = timezone.now()
    cutoff = now.date() + timedelta(days=LOOKAHEAD_DAYS)
    generated_total = 0

    for rule in rules:
        source = rule.post
        if not source.scheduled_at:
            continue

        # Respect end_date, but never look further than the rolling window.
        end = rule.end_date or cutoff
        if end > cutoff:
            end = cutoff

        base_date = source.scheduled_at.date()
        dates = _compute_recurrence_dates(base_date, rule.frequency, rule.interval, end)

        # Occurrences already materialised for *this* rule, identified by their
        # immutable occurrence date — independent of any later content edits.
        existing_dates = set(rule.generated_posts.values_list("recurrence_date", flat=True))

        for d in dates:
            if d in existing_dates or d <= now.date():
                continue
            if _generate_occurrence(rule, source, d):
                generated_total += 1

        rule.last_generated_at = now
        rule.save(update_fields=["last_generated_at"])

    logger.info("Generated %d recurring posts.", generated_total)
    return generated_total


def _generate_occurrence(rule, source, occurrence_date):
    """Clone ``source`` into a new Post for ``occurrence_date``.

    The whole occurrence — base Post, per-platform children (with their time
    offsets preserved) and media attachments — is created in a single atomic
    block tagged with the ``(rule, occurrence_date)`` lineage. If a concurrent
    run already created the same occurrence the partial unique constraint
    raises ``IntegrityError``; we treat that as "already generated" and skip.

    Returns ``True`` if a new occurrence was created, ``False`` otherwise.
    """
    base_time = source.scheduled_at.time()
    base_tz = source.scheduled_at.tzinfo

    scheduled_dt = datetime.combine(occurrence_date, base_time)
    if base_tz:
        scheduled_dt = scheduled_dt.replace(tzinfo=base_tz)

    try:
        with transaction.atomic():
            new_post = Post.objects.create(
                workspace=source.workspace,
                author=source.author,
                caption=source.caption,
                first_comment=source.first_comment,
                internal_notes=source.internal_notes,
                tags=source.tags,
                category=source.category,
                scheduled_at=scheduled_dt,
                recurrence_source=rule,
                recurrence_date=occurrence_date,
            )

            # Clone platform posts in bulk, preserving per-platform offsets so
            # each recurrence keeps the same per-platform time deltas.
            source_pps = list(source.platform_posts.all())
            if source_pps:
                new_pps = []
                for pp in source_pps:
                    pp_scheduled = None
                    if pp.scheduled_at and source.scheduled_at:
                        delta = pp.scheduled_at - source.scheduled_at
                        pp_scheduled = scheduled_dt + delta
                    new_pps.append(
                        PlatformPost(
                            post=new_post,
                            social_account=pp.social_account,
                            platform_specific_caption=pp.platform_specific_caption,
                            platform_specific_first_comment=pp.platform_specific_first_comment,
                            platform_specific_media=pp.platform_specific_media,
                            scheduled_at=pp_scheduled,
                            status="scheduled",
                        )
                    )
                PlatformPost.objects.bulk_create(new_pps)

                # Sync Post.scheduled_at to the earliest child time.
                sync_post_scheduled_at(new_post)

            # Clone media attachments in bulk.
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
    except IntegrityError:
        logger.debug(
            "Recurrence occurrence %s for rule %s already exists; skipping.",
            occurrence_date,
            rule.id,
        )
        return False

    return True


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
