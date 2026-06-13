"""Background tasks for the composer.

Currently just the on-demand CSV bulk-import worker. Thin wrapper over the pure
engine in ``apps.composer.csv_import`` — the view enqueues this by id, the
worker (``manage.py process_tasks``) runs it.
"""

import logging

from background_task import background

logger = logging.getLogger(__name__)


@background(schedule=0)
def process_csv_import_job_task(job_id: str):
    """Process a persisted :class:`CSVImportJob` in the background.

    Re-fetches the job by id (the enqueue path only stores serializable args)
    and delegates to the engine, which owns all status/progress/result writes.
    """
    from .csv_import import process_csv_import_job
    from .models import CSVImportJob

    try:
        job = CSVImportJob.objects.get(id=job_id)
    except CSVImportJob.DoesNotExist:
        logger.warning("CSV import task: job %s not found, skipping", job_id)
        return

    process_csv_import_job(job)
