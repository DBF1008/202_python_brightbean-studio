"""Background tasks for CSV import processing."""

import csv
import io
import logging
import zoneinfo
from datetime import datetime, time as time_cls

from background_task import background
from django.db import transaction

logger = logging.getLogger(__name__)

# Cap the number of per-row error records we persist to keep JSON small.
_MAX_ERROR_DETAILS = 100


@background(schedule=0)
def process_csv_import(job_id: str):
    """Process a persisted CSV import job row-by-row.

    Creates ``Post`` and ``PlatformPost`` records for every valid row,
    tracks progress on the ``CSVImportJob`` model, and isolates errors
    so a single bad row does not abort the entire import.
    """
    # Lazy imports to avoid circular-import issues with the worker process.
    from apps.composer.models import (
        CSVImportJob,
        ContentCategory,
        PlatformPost,
        Post,
    )
    from apps.composer.services import sync_post_scheduled_at
    from apps.social_accounts.models import SocialAccount

    try:
        job = CSVImportJob.objects.get(id=job_id)
    except CSVImportJob.DoesNotExist:
        logger.warning("CSVImportJob %s not found", job_id)
        return

    # Transition to PROCESSING.
    job.status = CSVImportJob.Status.PROCESSING
    job.save(update_fields=["status"])

    created = 0
    errors = 0
    error_details: list[dict] = []

    try:
        # ------------------------------------------------------------------
        # Read the CSV from the persisted file.
        # ------------------------------------------------------------------
        job.file.open("r")
        try:
            raw = job.file.read()
        finally:
            job.file.close()

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")

        reader = csv.reader(io.StringIO(raw))
        rows = list(reader)

        if not rows:
            job.status = CSVImportJob.Status.FAILED
            job.result_summary = {"created": 0, "errors": 0, "warnings": ["CSV file is empty."]}
            job.save(update_fields=["status", "result_summary"])
            return

        # First row is the header; data rows start at index 1.
        data_rows = rows[1:]
        job.total_rows = len(data_rows)
        job.save(update_fields=["total_rows"])

        mapping: dict = job.column_mapping  # field_name -> column index
        workspace = job.workspace
        author = job.uploaded_by
        ws_tz_name = workspace.effective_timezone or "UTC"
        tz = zoneinfo.ZoneInfo(ws_tz_name)

        # ------------------------------------------------------------------
        # Pre-fetch connected accounts for the workspace (avoid N+1).
        # ------------------------------------------------------------------
        connected_accounts_qs = SocialAccount.objects.filter(
            workspace=workspace,
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        # Build lookup: platform_slug -> [account, ...]
        accounts_by_platform: dict[str, list] = {}
        for acc in connected_accounts_qs:
            accounts_by_platform.setdefault(acc.platform, []).append(acc)

        # ------------------------------------------------------------------
        # Process each row.
        # ------------------------------------------------------------------
        for row_idx, row in enumerate(data_rows, start=2):
            try:
                created_ok = _process_row(
                    row=row,
                    row_idx=row_idx,
                    mapping=mapping,
                    workspace=workspace,
                    author=author,
                    tz=tz,
                    accounts_by_platform=accounts_by_platform,
                )
                if created_ok:
                    created += 1
                else:
                    errors += 1
                    if len(error_details) < _MAX_ERROR_DETAILS:
                        error_details.append({"row": row_idx, "error": "Caption is empty or row could not be processed."})
            except Exception as exc:
                errors += 1
                if len(error_details) < _MAX_ERROR_DETAILS:
                    error_details.append({"row": row_idx, "error": str(exc)})

            # Persist progress every row so the polling endpoint stays fresh.
            job.processed_rows = row_idx - 1  # 1-based count of data rows handled
            job.save(update_fields=["processed_rows"])

        # ------------------------------------------------------------------
        # Finalize.
        # ------------------------------------------------------------------
        job.status = CSVImportJob.Status.COMPLETED
        job.result_summary = {
            "created": created,
            "errors": errors,
            "warnings": [],
        }
        job.error_details = error_details
        job.save(update_fields=["status", "result_summary", "error_details"])
        logger.info("CSVImportJob %s completed: %d created, %d errors", job.id, created, errors)

    except Exception:
        logger.exception("CSVImportJob %s failed fatally", job_id)
        job.status = CSVImportJob.Status.FAILED
        job.result_summary = {
            "created": created,
            "errors": errors,
            "warnings": ["Job terminated due to an unexpected error."],
        }
        job.error_details = error_details
        job.save(update_fields=["status", "result_summary", "error_details"])


def _process_row(
    *,
    row: list[str],
    row_idx: int,
    mapping: dict,
    workspace,
    author,
    tz,
    accounts_by_platform: dict[str, list],
) -> bool:
    """Create a Post + PlatformPosts for a single CSV row.

    Returns ``True`` if the row was successfully imported, ``False`` if
    the row was skipped (e.g. empty caption).
    """
    from apps.composer.models import ContentCategory, PlatformPost, Post
    from apps.composer.services import sync_post_scheduled_at

    # -- Caption (required) --------------------------------------------------
    caption = _col(row, mapping, "caption")
    if not caption:
        return False

    post = Post(workspace=workspace, author=author, caption=caption)
    initial_pp_status = "draft"

    # -- Date + time ---------------------------------------------------------
    date_str = _col(row, mapping, "date")
    if date_str:
        time_str = _col(row, mapping, "time")
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        t = datetime.strptime(time_str, "%H:%M").time() if time_str else time_cls(9, 0)
        naive_dt = datetime.combine(d, t)
        post.scheduled_at = naive_dt.replace(tzinfo=tz)
        initial_pp_status = "scheduled"

    # -- First comment -------------------------------------------------------
    fc = _col(row, mapping, "first_comment")
    if fc:
        post.first_comment = fc

    # -- Tags ----------------------------------------------------------------
    tags_raw = _col(row, mapping, "tags")
    if tags_raw:
        post.tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

    # -- Category (get_or_create) --------------------------------------------
    cat_name = _col(row, mapping, "category")
    if cat_name:
        cat, _ = ContentCategory.objects.get_or_create(
            workspace=workspace,
            name=cat_name,
            defaults={"color": "#3B82F6"},
        )
        post.category = cat

    post.save()

    # -- Platforms -----------------------------------------------------------
    platforms_str = _col(row, mapping, "platforms")
    if platforms_str:
        for p in platforms_str.split(","):
            p = p.strip().lower()
            if not p:
                continue
            accounts = accounts_by_platform.get(p, [])
            for acc in accounts:
                PlatformPost.objects.get_or_create(
                    post=post,
                    social_account=acc,
                    defaults={
                        "status": initial_pp_status,
                        "scheduled_at": post.scheduled_at,
                    },
                )

    # Keep Post.scheduled_at consistent with earliest PlatformPost.
    sync_post_scheduled_at(post)

    return True


def _col(row: list[str], mapping: dict, field: str) -> str:
    """Safely extract a mapped column value from a row."""
    idx = mapping.get(field)
    if idx is None or idx >= len(row):
        return ""
    return row[idx].strip()
