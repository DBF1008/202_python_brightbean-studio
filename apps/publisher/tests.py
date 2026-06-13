"""Tests for the Publishing Engine (T-1A.3)."""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.publisher.engine import (
    MAX_RETRIES,
    RETRY_BACKOFF,
    PublishEngine,
    _SettingResolver,
)
from apps.publisher.models import PublishLog, RateLimitState
from apps.settings_manager.helpers import parse_backoff_schedule
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


# ---------------------------------------------------------------------------
# Settings cascade integration tests
# ---------------------------------------------------------------------------


class ParseBackoffScheduleTest(SimpleTestCase):
    """Pure-function tests for ``parse_backoff_schedule``."""

    def test_standard_human_format(self):
        self.assertEqual(parse_backoff_schedule("1min,5min,30min"), [60, 300, 1800])

    def test_bare_seconds(self):
        self.assertEqual(parse_backoff_schedule("60,300,1800"), [60, 300, 1800])

    def test_mixed_units(self):
        self.assertEqual(parse_backoff_schedule("30s,2min,1h"), [30, 120, 3600])

    def test_list_passthrough(self):
        self.assertEqual(parse_backoff_schedule([60, 300, 1800]), [60, 300, 1800])

    def test_list_of_strings_passthrough(self):
        self.assertEqual(parse_backoff_schedule(["60", "300"]), [60, 300])

    def test_malformed_returns_fallback(self):
        self.assertEqual(parse_backoff_schedule("garbage"), [60, 300, 1800])

    def test_empty_string_returns_fallback(self):
        self.assertEqual(parse_backoff_schedule(""), [60, 300, 1800])

    def test_none_returns_fallback(self):
        self.assertEqual(parse_backoff_schedule(None), [60, 300, 1800])

    def test_custom_fallback(self):
        self.assertEqual(parse_backoff_schedule("bad", fallback=[10, 20]), [10, 20])

    def test_whitespace_tolerant(self):
        self.assertEqual(parse_backoff_schedule(" 1min , 5min "), [60, 300])

    def test_hours(self):
        self.assertEqual(parse_backoff_schedule("1h,2hr"), [3600, 7200])


class ModuleConstantCompatTest(SimpleTestCase):
    """Ensure module-level aliases still match APP_DEFAULTS (backward compat)."""

    def test_retry_backoff_matches_app_defaults(self):
        self.assertEqual(RETRY_BACKOFF, [60, 300, 1800])

    def test_max_retries_matches_app_defaults(self):
        self.assertEqual(MAX_RETRIES, 3)


class SettingResolverUnitTest(SimpleTestCase):
    """Unit tests for ``_SettingResolver`` caching and typed accessors."""

    @patch("apps.publisher.engine.get_setting")
    def test_caches_per_workspace_key(self, mock_get):
        mock_get.return_value = 5
        resolver = _SettingResolver()
        self.assertEqual(resolver.get("ws1", "publishing.retry_max_attempts"), 5)
        self.assertEqual(resolver.get("ws1", "publishing.retry_max_attempts"), 5)
        mock_get.assert_called_once_with("ws1", "publishing.retry_max_attempts")

    @patch("apps.publisher.engine.get_setting")
    def test_get_max_retries_clamps_to_one(self, mock_get):
        mock_get.return_value = 0
        resolver = _SettingResolver()
        self.assertEqual(resolver.get_max_retries("ws1"), 1)

    @patch("apps.publisher.engine.get_setting")
    def test_get_max_retries_invalid_falls_back(self, mock_get):
        mock_get.return_value = "not-a-number"
        resolver = _SettingResolver()
        self.assertEqual(resolver.get_max_retries("ws1"), 3)

    @patch("apps.publisher.engine.get_setting")
    def test_get_first_comment_delay_negative_clamps(self, mock_get):
        mock_get.return_value = -5
        resolver = _SettingResolver()
        self.assertEqual(resolver.get_first_comment_delay("ws1"), 0)

    @patch("apps.publisher.engine.get_setting")
    def test_get_backoff_parses_human_string(self, mock_get):
        mock_get.return_value = "10s,20s,40s"
        resolver = _SettingResolver()
        self.assertEqual(resolver.get_backoff("ws1"), [10, 20, 40])


class PerWorkspaceRetryTest(TestCase):
    """Verify ``_schedule_retry`` honours workspace-level overrides."""

    def setUp(self):
        from apps.composer.models import PlatformPost, Post
        from apps.organizations.models import Organization
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        self.org = Organization.objects.create(name="RetryOrg")
        self.workspace = Workspace.objects.create(organization=self.org, name="RetryWS")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="tiktok",
            account_platform_id="tt-r1",
            account_name="retryaccount",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.post = Post.objects.create(workspace=self.workspace, caption="retry test")
        self.platform_post = PlatformPost.objects.create(
            post=self.post,
            social_account=self.account,
            status=PlatformPost.Status.PUBLISHING,
        )

    @patch("apps.publisher.engine.get_setting")
    def test_workspace_max_retries_override(self, mock_get):
        """A workspace with max_retries=5 should allow more retries than default 3."""
        from apps.composer.models import PlatformPost
        from providers.exceptions import PublishError

        def side_effect(ws_id, key):
            mapping = {
                "publishing.retry_max_attempts": 5,
                "publishing.retry_backoff_schedule": "10s,20s,30s,40s,50s",
            }
            return mapping.get(key)

        mock_get.side_effect = side_effect

        engine = PublishEngine()
        error = PublishError("transient", platform="TikTok")
        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=error):
            engine._publish_platform_post(self.platform_post)

        self.platform_post.refresh_from_db()
        self.assertEqual(self.platform_post.status, PlatformPost.Status.SCHEDULED)
        self.assertEqual(self.platform_post.retry_count, 1)
        # Backoff should be 10 seconds (first entry)
        expected = timezone.now() + timedelta(seconds=10)
        self.assertAlmostEqual(
            self.platform_post.next_retry_at.timestamp(),
            expected.timestamp(),
            delta=2,
        )

    @patch("apps.publisher.engine.get_setting")
    def test_workspace_backoff_schedule_override(self, mock_get):
        """Custom backoff schedule is used instead of the default."""
        from apps.composer.models import PlatformPost
        from providers.exceptions import PublishError

        def side_effect(ws_id, key):
            mapping = {
                "publishing.retry_max_attempts": 2,
                "publishing.retry_backoff_schedule": "300s,600s",
            }
            return mapping.get(key)

        mock_get.side_effect = side_effect

        engine = PublishEngine()
        self.platform_post.retry_count = 1  # simulate second attempt
        self.platform_post.save()

        error = PublishError("transient", platform="TikTok")
        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=error):
            engine._publish_platform_post(self.platform_post)

        self.platform_post.refresh_from_db()
        self.assertEqual(self.platform_post.retry_count, 2)
        # Second entry of [300, 600] -> 600 seconds
        expected = timezone.now() + timedelta(seconds=600)
        self.assertAlmostEqual(
            self.platform_post.next_retry_at.timestamp(),
            expected.timestamp(),
            delta=2,
        )

    @patch("apps.publisher.engine.get_setting")
    def test_exhausted_workspace_retries_fail_permanently(self, mock_get):
        """When workspace max_retries is reached, post fails permanently."""
        from apps.composer.models import PlatformPost
        from providers.exceptions import PublishError

        mock_get.side_effect = lambda ws_id, key: {
            "publishing.retry_max_attempts": 2,
            "publishing.retry_backoff_schedule": "10s,20s",
        }.get(key)

        engine = PublishEngine()
        self.platform_post.retry_count = 2  # already at max
        self.platform_post.save()

        error = PublishError("transient", platform="TikTok")
        with patch.object(PublishEngine, "_dispatch_to_provider", side_effect=error):
            engine._publish_platform_post(self.platform_post)

        self.platform_post.refresh_from_db()
        self.assertEqual(self.platform_post.status, PlatformPost.Status.FAILED)
        self.assertEqual(self.platform_post.retry_count, 2)


class PerWorkspaceFirstCommentDelayTest(TestCase):
    """Verify first comment scheduling uses workspace-level delay."""

    def setUp(self):
        from apps.composer.models import PlatformPost, Post
        from apps.organizations.models import Organization
        from apps.social_accounts.models import SocialAccount
        from apps.workspaces.models import Workspace

        self.org = Organization.objects.create(name="FCOrg")
        self.workspace = Workspace.objects.create(organization=self.org, name="FCWS")
        self.account = SocialAccount.objects.create(
            workspace=self.workspace,
            platform="instagram",
            account_platform_id="ig-fc1",
            account_name="fcaccount",
            connection_status=SocialAccount.ConnectionStatus.CONNECTED,
        )
        self.post = Post.objects.create(
            workspace=self.workspace,
            caption="first comment test",
            first_comment="Hello!",
        )
        self.platform_post = PlatformPost.objects.create(
            post=self.post,
            social_account=self.account,
            status=PlatformPost.Status.PUBLISHED,
            platform_post_id="ext-123",
        )

    @patch("apps.publisher.engine._post_first_comment_task")
    @patch("apps.publisher.engine.get_setting")
    def test_custom_first_comment_delay(self, mock_get, mock_task):
        mock_get.side_effect = lambda ws_id, key: {
            "publishing.first_comment_delay_seconds": 300,
        }.get(key)

        engine = PublishEngine()
        engine._resolver = _SettingResolver()  # initialize resolver

        # Simulate _publish_post_group's first comment scheduling path
        pp = self.platform_post
        pp.refresh_from_db()
        with patch.object(pp.social_account, "supports_first_comment", return_value=True):
            comment_text = pp.effective_first_comment
            if comment_text:
                delay = engine._get_resolver().get_first_comment_delay(pp.post.workspace_id)
                mock_task(str(pp.id), schedule=delay)

        mock_task.assert_called_once_with(str(pp.id), schedule=300)
