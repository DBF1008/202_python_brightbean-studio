from django.apps import AppConfig


class ComposerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.composer"
    verbose_name = "Post Composer"

    def ready(self):
        # Import the tasks module so the @background CSV-import task registers
        # itself with the worker (process_tasks). It's enqueued on demand by the
        # confirm view, so unlike the recurring tasks it needs no scheduling.
        from . import tasks  # noqa: F401
