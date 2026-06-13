"""CSV bulk-import engine.

Pure, directly-testable processing logic for a persisted :class:`CSVImportJob`.
The HTTP view (``csv_confirm_import``) creates and persists the job (file +
column mapping + total row count); a thin ``@background`` wrapper in
``apps.composer.tasks`` re-fetches the job by id and calls
:func:`process_csv_import_job` here.

The engine reads the job's own file (the source of truth — decoupled from the
upload session), walks the rows, and creates one ``Post`` plus one
``PlatformPost`` per connected target account. It mirrors the established
"task → pure engine" split used by ``apps.publisher`` so the row logic can be
unit-tested without running a worker.

Semantics preserved from the original synchronous import:

* empty-caption rows are skipped and counted as errors;
* a date column promotes the row to ``scheduled`` (default time 09:00),
  localized to the workspace timezone; otherwise the platform posts start as
  ``draft``;
* categories are created on demand, tags are comma-split, and platforms map to
  *connected* social accounts only;
* each row is processed in its own savepoint so one bad row never rolls back
  the others (error isolation).

Progress is committed incrementally (``processed_rows`` after every row) so a
polling status endpoint sees live progress — the loop is deliberately NOT
wrapped in a single outer transaction.
"""

import csv
import io
import logging
import zoneinfo
from datetime import datetime
from datetime import time as time_cls

from django.db import transaction

logger = logging.getLogger(__name__)

# Cap stored warnings so result_summary JSON stays bounded even for a CSV that
# is wall-to-wall errors (mirrors the 50-error cap in the validation preview).
MAX_WARNINGS = 100


def _cell(row, mapping, field):
    """Return the stripped value for ``field`` or ``""`` if unmapped/out of range."""
    idx = mapping.get(field)
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()


def process_csv_import_job(job):
    """Process a persisted ``CSVImportJob`` row by row.

    Updates ``status`` (processing → completed/failed), ``total_rows``,
    ``processed_rows`` (incrementally), and ``result_summary``
    (``{"created", "errors", "warnings"}``). Returns the job.
    """
    from apps.social_accounts.models import SocialAccount

    from .models import ContentCategory, CSVImportJob, PlatformPost, Post

    # Idempotency: never reprocess a job that already finished successfully.
    if job.status == CSVImportJob.Status.COMPLETED:
        return job

    job.status = CSVImportJob.Status.PROCESSING
    job.processed_rows = 0
    job.save(update_fields=["status", "processed_rows"])

    # Read + parse the job's own file. A failure here is fatal for the job.
    try:
        with job.file.open("rb") as fh:
            decoded = fh.read().decode("utf-8-sig")
        all_rows = list(csv.reader(io.StringIO(decoded)))
    except Exception as exc:
        logger.exception("CSV import job %s: failed to read file", job.id)
        job.status = CSVImportJob.Status.FAILED
        job.result_summary = {
            "created": 0,
            "errors": 0,
            "warnings": [f"Could not read CSV file: {exc}"],
        }
        job.save(update_fields=["status", "result_summary"])
        return job

    data_rows = all_rows[1:]  # row 0 is the header (written at confirm time)
    # Self-correct the denominator so the progress bar always matches what we
    # actually iterate, even if the persisted file drifted from the recorded total.
    if job.total_rows != len(data_rows):
        job.total_rows = len(data_rows)
        job.save(update_fields=["total_rows"])

    workspace = job.workspace
    mapping = job.column_mapping or {}
    tz = zoneinfo.ZoneInfo(workspace.effective_timezone or "UTC")

    created = 0
    errors = 0
    warnings: list[str] = []

    # ``start=2``: row 1 is the header, so the first data row is row 2 — keeps
    # warning row numbers aligned with what the user sees in a spreadsheet.
    for row_number, row in enumerate(data_rows, start=2):
        caption = _cell(row, mapping, "caption")
        if not caption:
            errors += 1
            if len(warnings) < MAX_WARNINGS:
                warnings.append(f"Row {row_number}: caption is empty")
        else:
            try:
                with transaction.atomic():
                    post = Post(
                        workspace=workspace,
                        author=job.uploaded_by,
                        caption=caption,
                    )
                    initial_pp_status = "draft"

                    # Date (+ optional time) → workspace-local scheduled_at.
                    date_str = _cell(row, mapping, "date")
                    if date_str:
                        time_str = _cell(row, mapping, "time")
                        d = datetime.strptime(date_str, "%Y-%m-%d").date()
                        t = datetime.strptime(time_str, "%H:%M").time() if time_str else time_cls(9, 0)
                        post.scheduled_at = datetime.combine(d, t).replace(tzinfo=tz)
                        initial_pp_status = "scheduled"

                    first_comment = _cell(row, mapping, "first_comment")
                    if first_comment:
                        post.first_comment = first_comment

                    tags_raw = _cell(row, mapping, "tags")
                    if tags_raw:
                        post.tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

                    cat_name = _cell(row, mapping, "category")
                    if cat_name:
                        category, _ = ContentCategory.objects.get_or_create(
                            workspace=workspace,
                            name=cat_name,
                            defaults={"color": "#3B82F6"},
                        )
                        post.category = category

                    post.save()

                    platforms_str = _cell(row, mapping, "platforms")
                    if platforms_str:
                        for raw_platform in platforms_str.split(","):
                            platform = raw_platform.strip().lower()
                            if not platform:
                                continue
                            accounts = SocialAccount.objects.filter(
                                workspace=workspace,
                                platform=platform,
                                connection_status=SocialAccount.ConnectionStatus.CONNECTED,
                            )
                            for account in accounts:
                                PlatformPost.objects.get_or_create(
                                    post=post,
                                    social_account=account,
                                    defaults={
                                        "status": initial_pp_status,
                                        "scheduled_at": post.scheduled_at,
                                    },
                                )
                created += 1
            except Exception as exc:
                # Per-row isolation: the atomic block above already rolled this
                # row's partial inserts back; just record it and move on.
                errors += 1
                if len(warnings) < MAX_WARNINGS:
                    warnings.append(f"Row {row_number}: {exc}")

        # Commit progress after every row (outside the per-row savepoint) so the
        # polling endpoint can watch processed_rows climb in real time.
        job.processed_rows = row_number - 1
        job.save(update_fields=["processed_rows"])

    job.status = CSVImportJob.Status.COMPLETED
    job.result_summary = {"created": created, "errors": errors, "warnings": warnings}
    job.save(update_fields=["status", "result_summary"])
    logger.info(
        "CSV import job %s completed: %d created, %d error(s)",
        job.id,
        created,
        errors,
    )
    return job
