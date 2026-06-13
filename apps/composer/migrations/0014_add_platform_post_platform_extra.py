# Generated for YouTube-specific composer fields

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("composer", "0013_add_platform_post_scheduled_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="platformpost",
            name="platform_extra",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Per-platform metadata (privacy, tags, thumbnail_asset_id, etc.)",
            ),
        ),
    ]
