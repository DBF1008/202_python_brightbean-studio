import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("composer", "0016_alter_contentcategory_color"),
        ("calendar", "0003_queue_queueentry_recurrencerule_customcalendarevent"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="recurrence_source",
            field=models.ForeignKey(
                blank=True,
                help_text="The recurrence rule that generated this post (NULL for source/manual posts).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="generated_posts",
                to="calendar.recurrencerule",
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="recurrence_date",
            field=models.DateField(
                blank=True,
                help_text="The recurrence occurrence date this generated post represents.",
                null=True,
            ),
        ),
        migrations.AddConstraint(
            model_name="post",
            constraint=models.UniqueConstraint(
                condition=models.Q(("recurrence_source__isnull", False)),
                fields=("recurrence_source", "recurrence_date"),
                name="uniq_post_recurrence_source_date",
            ),
        ),
    ]
