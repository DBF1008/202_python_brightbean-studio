# Generated migration to replace avatar_url URLField with avatar ImageField

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="user",
            name="avatar_url",
        ),
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(blank=True, upload_to="avatars/%Y/%m/"),
        ),
    ]
