"""Idempotency + lineage tests for recurring post generation (apps/calendar/tasks.py).

These cover the failure modes the content-based dedup used to have:

* re-running the daily task must not duplicate occurrences,
* editing the source post (caption / category / attachments) must not break
  lineage or cause duplicates, and
* two distinct posts that happen to share a caption must each generate their
  own full series instead of cannibalising one another.
"""

from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.calendar.models import RecurrenceRule
from apps.calendar.tasks import generate_recurring_posts
from apps.composer.models import ContentCategory, PlatformPost, Post, PostMedia
from apps.media_library.models import MediaAsset
from apps.organizations.models import Organization
from apps.social_accounts.models import SocialAccount
from apps.workspaces.models import Workspace

PLATFORM_OFFSET = timedelta(hours=2)


class RecurringPostGenerationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="recurrence@example.com",
            password="testpass123",
            tos_accepted_at=timezone.now(),
        )
        self.org = Organization.objects.create(name="Org")
        self.ws = Workspace.objects.create(organization=self.org, name="WS")
        self.account = SocialAccount.objects.create(
            workspace=self.ws,
            platform="instagram",
            account_platform_id="ig-1",
            account_name="IG",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.category = ContentCategory.objects.create(workspace=self.ws, name="Edu")
        self.media = MediaAsset.objects.create(workspace=self.ws, filename="a.jpg", media_type="image")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_source(self, *, caption="Hello", with_children=True):
        """Create a future-scheduled source Post + weekly RecurrenceRule.

        Window is chosen so exactly three occurrences fall inside it
        (base+7, base+14, base+21 days), all strictly in the future.
        """
        base_dt = (timezone.now() + timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
        post = Post.objects.create(
            workspace=self.ws,
            author=self.user,
            caption=caption,
            category=self.category,
            scheduled_at=base_dt,
        )
        if with_children:
            PlatformPost.objects.create(
                post=post,
                social_account=self.account,
                scheduled_at=base_dt + PLATFORM_OFFSET,
                status="scheduled",
            )
            PostMedia.objects.create(post=post, media_asset=self.media, position=0, alt_text="alt")
        rule = RecurrenceRule.objects.create(
            post=post,
            frequency="weekly",
            interval=1,
            end_date=(base_dt + timedelta(days=21)).date(),
            is_active=True,
        )
        return post, rule, base_dt

    def _expected_dates(self, base_dt):
        base = base_dt.date()
        return {base + timedelta(days=7), base + timedelta(days=14), base + timedelta(days=21)}

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_generates_occurrences_with_lineage_and_clones(self):
        """First run creates one clone per occurrence, tagged with stable lineage,
        cloning platform sub-posts (with offset) and media attachments."""
        post, rule, base_dt = self._make_source()

        created = generate_recurring_posts()

        clones = Post.objects.filter(recurrence_source=rule)
        self.assertEqual(created, 3)
        self.assertEqual(clones.count(), 3)
        self.assertEqual(set(clones.values_list("recurrence_date", flat=True)), self._expected_dates(base_dt))

        base_time = base_dt.time()
        base_tz = base_dt.tzinfo
        for clone in clones:
            self.assertIsNone(post.recurrence_source)  # source itself is never tagged
            # Platform sub-post cloned with the per-platform offset preserved.
            pp = clone.platform_posts.get()
            self.assertEqual(pp.social_account_id, self.account.id)
            self.assertEqual(pp.status, "scheduled")
            occ_dt = datetime.combine(clone.recurrence_date, base_time).replace(tzinfo=base_tz)
            self.assertEqual(pp.scheduled_at, occ_dt + PLATFORM_OFFSET)
            # Post.scheduled_at synced to its single child's time.
            self.assertEqual(clone.scheduled_at, occ_dt + PLATFORM_OFFSET)
            # Media attachment cloned faithfully.
            pm = clone.media_attachments.get()
            self.assertEqual(pm.media_asset_id, self.media.id)
            self.assertEqual(pm.position, 0)
            self.assertEqual(pm.alt_text, "alt")

    def test_rerun_is_idempotent(self):
        """Running the task repeatedly must not create duplicate occurrences."""
        _, rule, _ = self._make_source()

        first = generate_recurring_posts()
        second = generate_recurring_posts()

        self.assertEqual(first, 3)
        self.assertEqual(second, 0)
        self.assertEqual(Post.objects.filter(recurrence_source=rule).count(), 3)

    def test_source_content_edit_keeps_stable_lineage(self):
        """Editing the source's caption/category/attachments must not duplicate or
        skip occurrences — lineage is anchored on (rule, date), not content."""
        post, rule, base_dt = self._make_source(caption="Original")
        self.assertEqual(generate_recurring_posts(), 3)

        # Mutate every field the old dedup keyed on, plus attachments.
        post.caption = "Completely different caption"
        post.category = None
        post.save(update_fields=["caption", "category", "updated_at"])
        extra = MediaAsset.objects.create(workspace=self.ws, filename="b.jpg", media_type="image")
        PostMedia.objects.create(post=post, media_asset=extra, position=1, alt_text="second")

        second = generate_recurring_posts()

        self.assertEqual(second, 0)
        self.assertEqual(Post.objects.filter(recurrence_source=rule).count(), 3)
        for d in self._expected_dates(base_dt):
            self.assertEqual(
                Post.objects.filter(recurrence_source=rule, recurrence_date=d).count(),
                1,
                msg=f"occurrence {d} should exist exactly once",
            )

    def test_same_caption_distinct_rules_do_not_cross_skip(self):
        """Two posts sharing a caption must each generate their own full series.

        The old workspace+caption+date dedup made the second rule see the first
        rule's clones and skip them; the lineage-based dedup keeps them separate.
        """
        _, rule_a, base_a = self._make_source(caption="Identical caption", with_children=False)
        _, rule_b, base_b = self._make_source(caption="Identical caption", with_children=False)
        # Sources are scheduled within the same minute → identical occurrence dates.
        self.assertEqual(self._expected_dates(base_a), self._expected_dates(base_b))

        generate_recurring_posts()

        self.assertEqual(Post.objects.filter(recurrence_source=rule_a).count(), 3)
        self.assertEqual(Post.objects.filter(recurrence_source=rule_b).count(), 3)
        self.assertEqual(
            set(Post.objects.filter(recurrence_source=rule_a).values_list("recurrence_date", flat=True)),
            self._expected_dates(base_a),
        )

    def test_unique_constraint_blocks_duplicate_occurrence_but_allows_manual_posts(self):
        """DB-level guarantee: no two posts per (rule, date); manual posts (NULL
        source) are unconstrained so any number can coexist."""
        _, rule, _ = self._make_source(with_children=False)
        generate_recurring_posts()
        existing = Post.objects.filter(recurrence_source=rule).first()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Post.objects.create(
                    workspace=self.ws,
                    recurrence_source=rule,
                    recurrence_date=existing.recurrence_date,
                )

        # Two manual posts with NULL lineage must both be allowed.
        Post.objects.create(workspace=self.ws, caption="manual one")
        Post.objects.create(workspace=self.ws, caption="manual two")
