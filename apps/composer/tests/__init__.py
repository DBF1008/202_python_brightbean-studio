"""Tests for the Post Composer app (T-1A.1)."""

from django.test import TestCase
from django.utils import timezone

from apps.composer.models import PlatformPost, Post, PostVersion
from apps.composer.status import derive_post_status


class PlatformPostStateMachineTest(TestCase):
    """Editorial status now lives on PlatformPost — every social account flows
    through the workflow independently. These tests target the per-platform
    state machine that used to live on Post.
    """

    def _make_pp(self, **kwargs):
        defaults = {"status": PlatformPost.Status.DRAFT}
        defaults.update(kwargs)
        return PlatformPost(**defaults)

    def test_valid_transitions_from_draft(self):
        pp = self._make_pp()
        self.assertTrue(pp.can_transition_to("pending_review"))
        self.assertTrue(pp.can_transition_to("scheduled"))
        self.assertTrue(pp.can_transition_to("publishing"))
        self.assertFalse(pp.can_transition_to("published"))
        self.assertFalse(pp.can_transition_to("failed"))

    def test_valid_transitions_from_scheduled(self):
        pp = self._make_pp(status="scheduled")
        self.assertTrue(pp.can_transition_to("publishing"))
        self.assertTrue(pp.can_transition_to("draft"))
        self.assertFalse(pp.can_transition_to("published"))

    def test_valid_transitions_from_publishing(self):
        pp = self._make_pp(status="publishing")
        self.assertTrue(pp.can_transition_to("published"))
        self.assertTrue(pp.can_transition_to("failed"))
        # Retry path: publishing → scheduled (picked up again on next tick)
        self.assertTrue(pp.can_transition_to("scheduled"))
        self.assertFalse(pp.can_transition_to("draft"))

    def test_transition_to_invalid_raises(self):
        pp = self._make_pp(status="draft")
        with self.assertRaises(ValueError) as ctx:
            pp.transition_to("published")
        self.assertIn("Invalid status transition", str(ctx.exception))

    def test_transition_to_published_sets_published_at(self):
        pp = self._make_pp(status="publishing")
        before = timezone.now()
        pp.transition_to("published")
        self.assertEqual(pp.status, "published")
        self.assertIsNotNone(pp.published_at)
        self.assertGreaterEqual(pp.published_at, before)

    def test_is_editable(self):
        for status in ("draft", "changes_requested", "rejected", "approved", "scheduled"):
            pp = self._make_pp(status=status)
            self.assertTrue(pp.is_editable, f"{status} should be editable")
        for status in ("publishing", "published", "failed"):
            pp = self._make_pp(status=status)
            self.assertFalse(pp.is_editable, f"{status} should not be editable")

    def test_is_schedulable(self):
        self.assertTrue(self._make_pp(status="draft").is_schedulable)
        self.assertTrue(self._make_pp(status="approved").is_schedulable)
        self.assertFalse(self._make_pp(status="published").is_schedulable)

    def test_status_color(self):
        pp = self._make_pp(status="draft")
        self.assertEqual(pp.status_color, "gray")
        pp.status = "published"
        self.assertEqual(pp.status_color, "green")
        pp.status = "failed"
        self.assertEqual(pp.status_color, "red")


class DerivePostStatusTest(TestCase):
    """`Post.status` is a derived aggregate over its PlatformPost children."""

    def test_empty_returns_draft(self):
        self.assertEqual(derive_post_status([]), "draft")

    def test_all_same_returns_that_status(self):
        self.assertEqual(derive_post_status(["draft", "draft"]), "draft")
        self.assertEqual(derive_post_status(["published", "published"]), "published")
        self.assertEqual(derive_post_status(["scheduled", "scheduled"]), "scheduled")

    def test_mixed_terminal_published_failed_is_partially_published(self):
        self.assertEqual(derive_post_status(["published", "failed"]), "partially_published")

    def test_all_failed_is_failed(self):
        self.assertEqual(derive_post_status(["failed", "failed"]), "failed")

    def test_mixed_workflow_returns_lowest(self):
        # draft is the most conservative state — it wins over scheduled.
        self.assertEqual(derive_post_status(["draft", "scheduled"]), "draft")
        # scheduled wins over publishing.
        self.assertEqual(derive_post_status(["scheduled", "publishing"]), "scheduled")
        # pending_review wins over approved.
        self.assertEqual(derive_post_status(["pending_review", "approved"]), "pending_review")


class PlatformPostModelTest(TestCase):
    """Test PlatformPost effective values and properties."""

    def test_effective_caption_falls_back(self):
        pp = PlatformPost()
        pp.platform_specific_caption = None
        post = Post(caption="Base caption")
        pp.post = post
        self.assertEqual(pp.effective_caption, "Base caption")

    def test_effective_caption_uses_override(self):
        pp = PlatformPost()
        pp.platform_specific_caption = "Override caption"
        post = Post(caption="Base caption")
        pp.post = post
        self.assertEqual(pp.effective_caption, "Override caption")

    def test_effective_first_comment_falls_back(self):
        pp = PlatformPost()
        pp.platform_specific_first_comment = None
        post = Post(first_comment="Base comment")
        pp.post = post
        self.assertEqual(pp.effective_first_comment, "Base comment")


class PostVersionModelTest(TestCase):
    """Test PostVersion snapshot model."""

    def test_str_representation(self):
        import uuid

        pv = PostVersion()
        pv.version_number = 3
        pv.post_id = uuid.uuid4()
        s = str(pv)
        self.assertIn("v3", s)
