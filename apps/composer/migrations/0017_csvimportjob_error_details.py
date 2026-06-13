"""Add error_details field to CSVImportJob."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("composer", "0016_alter_contentcategory_color"),
    ]

    operations = [
        migrations.AddField(
            model_name="csvimportjob",
            name="error_details",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Per-row error records, capped at 100 entries.",
            ),
        ),
    ]
