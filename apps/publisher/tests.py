"""Tests for the Publishing Engine (T-1A.3)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.publisher.config import (
    DEFAULT_RETRY_BACKOFF,
    parse_backoff_schedule,
    resolve_max_concurrent_publish_jobs,
    resolve_publish_config,
)
from apps.publisher.engine import MAX_RETRIES, RETRY_BACKOFF, PublishEngine
from apps.publisher.models import PublishLog, RateLimitState
from providers.types import AuthType, PostType, PublishResult


class RateLimitStateModelTest(TestCase):
    """Test RateLimitState model logic."""

    def test_is_rate_limited_when_zero_remaining_and_window_active(self):
        state = RateLimitState()
        state.requests_remaining = 0
        state.window_resets_at = timezone.now() + timedelta(minutes=5)
        self.assertTrue(state.is_rate_limited)

    def test_is_not_rate_limited_when_zero_remaining_and_window_expired(self):
        state = RateLimitState()
        state.requests_remaining = 0
        state.window_resets_at = timezone.now() - timedelta(minutes=5)
        self.assertFalse(state.is_rate_limited)

    def test_is_not_rate_limited_with_remaining_requests(self):
        state = RateLimitState()
        state.requests_remaining = 50
        state.window_resets_at = timezone.now() + timedelta(minutes=5)
        self.assertFalse(state.is_rate_limited)

    def test_can_publish_when_unknown(self):
        state = RateLimitState()
        state.requests_remaining = -1
        self.assertTrue(state.can_publish)

    def test_can_publish_when_remaining(self):
        state = RateLimitState()
        state.requests_remaining = 10
        self.assertTrue(state.can_publish)

    def test_cannot_publish_when_rate_limited(self):
        state = RateLimitState()
        state.requests_remaining = 0
        state.window_resets_at = timezone.now() + timedelta(minutes=5)
        self.assertFalse(state.can_publish)


class PublishEngineTest(TestCase):
    """Test PublishEngine core logic."""

    def test_retry_backoff_schedule(self):
        """Verify retry backoff values match spec."""
        self.assertEqual(RETRY_BACKOFF, [60, 300, 1800])
        self.assertEqual(MAX_RETRIES, 3)

    def test_engine_instantiates(self):
        engine = PublishEngine()
        self.assertIsNotNone(engine)

    @patch("apps.publisher.engine.PlatformPost.objects")
    def test_get_due_platform_posts_filters_correctly(self, mock_objects):
        """Engine should query PlatformPosts with a Coalesce effective_at filter."""
        engine = PublishEngine()
        mock_qs = MagicMock()
        mock_objects.filter.return_value = mock_qs
        mock_qs.annotate.return_value = mock_qs
        mock_qs.filter.return_value = mock_qs
        mock_qs.select_related.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.__getitem__ = MagicMock(return_value=[])

        engine._get_due_platform_posts()

        # First filter: editorial status (now lives on PlatformPost itself)
        first_call = mock_objects.filter.call_args_list[0]
        self.assertIn("status", first_call.kwargs)
        # Second filter (on annotated qs): effective_at__lte
        second_call = mock_qs.filter.call_args_list[0]
        self.assertIn("effective_at__lte", second_call.kwargs)


class PublishLogModelTest(TestCase):
    """Test PublishLog model."""

    def test_str_representation(self):
        log = PublishLog()
        log.attempt_number = 2
        log.status_code = 200
        s = str(log)
        self.assertIn("2", s)
        self.assertIn("200", s)


def _build_dispatch_mocks(platform: str, account_platform_id: str, platform_extra: dict | None = None):
    """Build the minimal mocks needed to exercise _dispatch_to_provider's
    extras-assembly without DB or filesystem side effects.

    Returns (engine, platform_post, mock_provider).
    """
    engine = PublishEngine()

    account = MagicMock()
    account.platform = platform
    account.account_platform_id = account_platform_id
    account.token_expires_at = None  # skip the OAuth refresh branch
    account.oauth_access_token = "tok"
    account.account_name = "Test Account"

    platform_post = MagicMock()
    platform_post.social_account = account
    platform_post.post.media_attachments.select_related.return_value.order_by.return_value = []
    platform_post.post.tags = []
    platform_post.effective_caption = "hello"
    platform_post.effective_title = None
    platform_post.effective_first_comment = None
    platform_post.platform_extra = platform_extra or {}

    mock_provider = MagicMock()
    mock_provider.auth_type = AuthType.OAUTH2
    mock_provider.supported_post_types = [PostType.TEXT]
    mock_provider.publish_post.return_value = PublishResult(
        platform_post_id="post-1",
        url="https://example.com/p/1",
        extra={},
    )
    return engine, platform_post, mock_provider


class DispatchExtraInjectionTest(SimpleTestCase):
    """Verify _dispatch_to_provider injects platform-specific extras."""

    @patch("apps.publisher.engine.get_provider")
    @patch("apps.publisher.engine._resolve_publish_credentials", return_value={})
    def test_injects_organization_author_for_linkedin_company(self, _mock_creds, mock_get_provider):
        engine, platform_post, mock_provider = _build_dispatch_mocks(
            platform="linkedin_company",
            account_platform_id="98765",
        )
        mock_get_provider.return_value = mock_provider

        engine._dispatch_to_provider(platform_post)

        mock_provider.publish_post.assert_called_once()
        _access_token, content = mock_provider.publish_post.call_args.args
        self.assertEqual(content.extra.get("author"), "urn:li:organization:98765")

    @patch("apps.publisher.engine.get_provider")
    @patch("apps.publisher.engine._resolve_publish_credentials", return_value={})
    def test_does_not_overwrite_explicit_author(self, _mock_creds, mock_get_provider):
        # When the caller has already set extra["author"], the engine must not
        # overwrite it — important for callers that pass a different URN.
        engine, platform_post, mock_provider = _build_dispatch_mocks(
            platform="linkedin_company",
            account_platform_id="98765",
            platform_extra={"author": "urn:li:organization:override"},
        )
        mock_get_provider.return_value = mock_provider

        engine._dispatch_to_provider(platform_post)

        _access_token, content = mock_provider.publish_post.call_args.args
        self.assertEqual(content.extra.get("author"), "urn:li:organization:override")

    @patch("apps.publisher.engine.get_provider")
    @patch("apps.publisher.engine._resolve_publish_credentials", return_value={})
    def test_does_not_inject_author_for_other_platforms(self, _mock_creds, mock_get_provider):
        # Sanity: the author-injection branch is scoped to linkedin_company only.
        engine, platform_post, mock_provider = _build_dispatch_mocks(
            platform="linkedin_personal",
            account_platform_id="11111",
        )
        mock_get_provider.return_value = mock_provider

        engine._dispatch_to_provider(platform_post)

        _access_token, content = mock_provider.publish_post.call_args.args
        self.assertNotIn("author", content.extra)


class NonRetryableFailureTest(TestCase):
    """_publish_platform_post must honor the exception's ``retryable`` flag."""

    def setUp(self):
        from apps.composer.models import PlatformPost, Post
        from apps.organizations.models import Organization
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        self.org = Organization.objects.create(name="Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="WS")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="tiktok",
            account_platform_id="tt-1",
            account_name="janschmitz51",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.post = Post.objects.create(workspace=self.workspace, caption="hi")
        self.platform_post = PlatformPost.objects.create(
            post=self.post,
            social_account=self.account,
            status=PlatformPost.Status.PUBLISHING,
        )

    def test_non_retryable_error_fails_immediately(self):
        from apps.composer.models import PlatformPost
        from providers.exceptions import PublishError

        engine = PublishEngine()
        error = PublishError("TikTok rejected the post: audit pending", platform="TikTok", retryable=False)
        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=error):
            result = engine._publish_platform_post(self.platform_post)

        self.assertFalse(result["success"])
        self.platform_post.refresh_from_db()
        self.assertEqual(self.platform_post.status, PlatformPost.Status.FAILED)
        self.assertEqual(self.platform_post.retry_count, 0)
        self.assertIsNone(self.platform_post.next_retry_at)
        self.assertIn("audit pending", self.platform_post.publish_error)
        self.assertEqual(PublishLog.objects.filter(platform_post=self.platform_post).count(), 1)

    def test_retryable_error_schedules_backoff_retry(self):
        from apps.composer.models import PlatformPost
        from providers.exceptions import PublishError

        engine = PublishEngine()
        error = PublishError("transient", platform="TikTok")
        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=error):
            result = engine._publish_platform_post(self.platform_post)

        self.assertFalse(result["success"])
        self.platform_post.refresh_from_db()
        self.assertEqual(self.platform_post.status, PlatformPost.Status.SCHEDULED)
        self.assertEqual(self.platform_post.retry_count, 1)
        self.assertIsNotNone(self.platform_post.next_retry_at)
        self.assertEqual(PublishLog.objects.filter(platform_post=self.platform_post).count(), 1)


class BackoffScheduleParsingTest(SimpleTestCase):
    """parse_backoff_schedule tolerates the spec string form and edge cases."""

    def test_parses_spec_default_string(self):
        self.assertEqual(parse_backoff_schedule("1min,5min,30min"), [60, 300, 1800])

    def test_parses_mixed_units(self):
        self.assertEqual(parse_backoff_schedule("30s,2min,1h"), [30, 120, 3600])

    def test_skips_invalid_tokens(self):
        self.assertEqual(parse_backoff_schedule("5min,bogus,30s"), [300, 30])

    def test_empty_or_garbage_falls_back_to_default(self):
        self.assertEqual(parse_backoff_schedule(""), DEFAULT_RETRY_BACKOFF)
        self.assertEqual(parse_backoff_schedule("nope"), DEFAULT_RETRY_BACKOFF)

    def test_none_falls_back_to_default(self):
        self.assertEqual(parse_backoff_schedule(None), DEFAULT_RETRY_BACKOFF)

    def test_list_passthrough(self):
        self.assertEqual(parse_backoff_schedule([10, 20]), [10, 20])

    def test_returns_independent_default_list(self):
        # Must not hand back the shared module-level default list (mutation safety).
        result = parse_backoff_schedule(None)
        self.assertEqual(result, DEFAULT_RETRY_BACKOFF)
        self.assertIsNot(result, DEFAULT_RETRY_BACKOFF)


class MaxConcurrentPublishJobsTest(SimpleTestCase):
    """The global publish-batch size resolves at the application-default tier."""

    def test_default(self):
        self.assertEqual(resolve_max_concurrent_publish_jobs(), 10)


class PublishConfigCascadeTest(TestCase):
    """resolve_publish_config follows workspace -> org -> app default per key."""

    def setUp(self):
        from apps.organizations.models import Organization
        from apps.workspaces.models import Workspace

        self.org = Organization.objects.create(name="Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="WS")

    def test_defaults_when_no_overrides(self):
        cfg = resolve_publish_config(self.workspace.id, self.org.id)
        self.assertEqual(cfg.first_comment_delay, 120)
        self.assertEqual(cfg.retry_max_attempts, 3)
        self.assertEqual(cfg.retry_backoff, [60, 300, 1800])

    def test_resolve_without_org_id_looks_up_workspace(self):
        # Omitting the org id makes get_setting resolve it from the workspace.
        cfg = resolve_publish_config(self.workspace.id)
        self.assertEqual(cfg.retry_max_attempts, 3)

    def test_org_override_beats_default(self):
        from apps.settings_manager.models import OrgSetting

        OrgSetting.objects.create(organization=self.org, key="publishing.retry_max_attempts", value=5)
        OrgSetting.objects.create(organization=self.org, key="publishing.first_comment_delay_seconds", value=300)
        OrgSetting.objects.create(organization=self.org, key="publishing.retry_backoff_schedule", value="10s,20s")

        cfg = resolve_publish_config(self.workspace.id, self.org.id)
        self.assertEqual(cfg.retry_max_attempts, 5)
        self.assertEqual(cfg.first_comment_delay, 300)
        self.assertEqual(cfg.retry_backoff, [10, 20])

    def test_workspace_override_beats_org(self):
        from apps.settings_manager.models import OrgSetting, WorkspaceSetting

        OrgSetting.objects.create(organization=self.org, key="publishing.retry_max_attempts", value=5)
        WorkspaceSetting.objects.create(workspace=self.workspace, key="publishing.retry_max_attempts", value=7)

        cfg = resolve_publish_config(self.workspace.id, self.org.id)
        self.assertEqual(cfg.retry_max_attempts, 7)

    def test_different_workspaces_can_have_different_strategies(self):
        from apps.settings_manager.models import WorkspaceSetting
        from apps.workspaces.models import Workspace

        other = Workspace.objects.create(organization=self.org, name="WS2")
        WorkspaceSetting.objects.create(
            workspace=self.workspace,
            key="publishing.retry_backoff_schedule",
            value="10s,20s",
        )
        self.assertEqual(resolve_publish_config(self.workspace.id, self.org.id).retry_backoff, [10, 20])
        self.assertEqual(resolve_publish_config(other.id, self.org.id).retry_backoff, [60, 300, 1800])


class PerWorkspaceRetryPolicyTest(TestCase):
    """_schedule_retry honors the per-workspace retry config (failures + rate limits)."""

    def setUp(self):
        from apps.composer.models import Post
        from apps.organizations.models import Organization
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        self.org = Organization.objects.create(name="Org")
        self.workspace = Workspace.objects.create(organization=self.org, name="WS")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="tiktok",
            account_platform_id="tt-1",
            account_name="janschmitz51",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.post = Post.objects.create(workspace=self.workspace, caption="hi")

    def _make_pp(self, retry_count=0):
        from apps.composer.models import PlatformPost

        return PlatformPost.objects.create(
            post=self.post,
            social_account=self.account,
            status=PlatformPost.Status.PUBLISHING,
            retry_count=retry_count,
        )

    def test_workspace_max_attempts_fails_permanently(self):
        from apps.composer.models import PlatformPost
        from apps.settings_manager.models import WorkspaceSetting

        WorkspaceSetting.objects.create(workspace=self.workspace, key="publishing.retry_max_attempts", value=1)
        pp = self._make_pp(retry_count=1)

        PublishEngine()._schedule_retry(pp, "boom")

        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.FAILED)
        self.assertEqual(pp.retry_count, 1)

    def test_workspace_backoff_override_sets_next_retry(self):
        from apps.composer.models import PlatformPost
        from apps.settings_manager.models import WorkspaceSetting

        WorkspaceSetting.objects.create(
            workspace=self.workspace,
            key="publishing.retry_backoff_schedule",
            value="10s,20s",
        )
        pp = self._make_pp(retry_count=0)
        before = timezone.now()

        PublishEngine()._schedule_retry(pp, "boom")

        pp.refresh_from_db()
        self.assertEqual(pp.status, PlatformPost.Status.SCHEDULED)
        self.assertEqual(pp.retry_count, 1)
        # First override backoff entry is 10s.
        delta = (pp.next_retry_at - before).total_seconds()
        self.assertGreaterEqual(delta, 9)
        self.assertLessEqual(delta, 15)
