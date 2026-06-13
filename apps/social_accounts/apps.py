import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class SocialAccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.social_accounts"
    verbose_name = "Social Accounts"

    def ready(self):
        from django.db.models.signals import post_migrate

        post_migrate.connect(self._register_health_check_task, sender=self)

    @staticmethod
    def _register_health_check_task(sender, **kwargs):
        """Register the recurring health-check task after migrations are applied."""
        try:
            from background_task.models import Task

            from apps.social_accounts.tasks import schedule_all_health_checks

            if not Task.objects.filter(verbose_name="schedule_all_health_checks").exists():
                schedule_all_health_checks(
                    repeat=6 * 3600,
                    verbose_name="schedule_all_health_checks",
                )
                logger.info("Registered recurring health-check task (every 6h)")
        except Exception:
            logger.debug("Skipping health-check task registration (database not ready)")
