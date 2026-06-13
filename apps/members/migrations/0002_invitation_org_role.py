from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("members", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="invitation",
            name="org_role",
            field=models.CharField(
                choices=[("owner", "Owner"), ("admin", "Admin"), ("member", "Member")],
                default="member",
                max_length=20,
            ),
        ),
    ]
