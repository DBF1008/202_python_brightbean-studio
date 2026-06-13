from django.db import migrations, models

NEW_CHOICES = [
    ("facebook", "Facebook"),
    ("instagram", "Instagram"),
    ("linkedin_personal", "LinkedIn (Personal Profile)"),
    ("linkedin_company", "LinkedIn (Company Page)"),
    ("tiktok", "TikTok"),
    ("youtube", "YouTube"),
    ("pinterest", "Pinterest"),
    ("threads", "Threads"),
    ("bluesky", "Bluesky"),
    ("google_business", "Google Business Profile"),
    ("mastodon", "Mastodon"),
]


def rename_linkedin_to_company(apps, schema_editor):
    SocialAccount = apps.get_model("social_accounts", "SocialAccount")
    SocialAccount.objects.filter(platform="linkedin").update(platform="linkedin_company")


def rename_company_to_linkedin(apps, schema_editor):
    SocialAccount = apps.get_model("social_accounts", "SocialAccount")
    SocialAccount.objects.filter(platform="linkedin_company").update(platform="linkedin")


class Migration(migrations.Migration):
    dependencies = [
        ("social_accounts", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(rename_linkedin_to_company, rename_company_to_linkedin),
        migrations.AlterField(
            model_name="socialaccount",
            name="platform",
            field=models.CharField(choices=NEW_CHOICES, max_length=30),
        ),
    ]
