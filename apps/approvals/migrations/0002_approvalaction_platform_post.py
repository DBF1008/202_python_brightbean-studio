"""Add optional platform_post FK on ApprovalAction.

Now that editorial status lives on PlatformPost, approval decisions can target
a single platform instead of the whole Post. The new field is nullable so
historical actions (and bundled "apply to all platforms" decisions) are
represented with ``platform_post=NULL``.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("approvals", "0001_initial"),
        ("composer", "0015_per_account_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalaction",
            name="platform_post",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.deletion.CASCADE,
                related_name="approval_actions",
                to="composer.platformpost",
            ),
        ),
    ]
