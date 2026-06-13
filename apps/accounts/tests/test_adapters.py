"""Tests for the custom SocialAccountAdapter."""

import pytest
from allauth.socialaccount.models import SocialAccount as AllAuthSocialAccount
from allauth.socialaccount.models import SocialLogin
from django.test import RequestFactory

from apps.accounts.adapters import SocialAccountAdapter
from apps.accounts.models import OAuthConnection, User


@pytest.fixture
def adapter():
    return SocialAccountAdapter()


@pytest.fixture
def user(db):
    return User.objects.create_user(email="test@example.com", password="testpass123")


@pytest.fixture
def google_sociallogin(user):
    """Build a SocialLogin for Google without hitting the DB."""
    account = AllAuthSocialAccount(provider="google", uid="google-uid-123")
    sociallogin = SocialLogin(user=user, account=account)
    return sociallogin


@pytest.fixture
def request_factory():
    return RequestFactory()


@pytest.mark.django_db
class TestPopulateUser:
    def test_sets_name_from_google_profile(self, adapter, google_sociallogin, request_factory):
        request = request_factory.get("/")
        data = {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"}

        user = adapter.populate_user(request, google_sociallogin, data)

        assert user.name == "Jane Doe"

    def test_does_not_overwrite_existing_name(self, adapter, google_sociallogin, request_factory):
        request = request_factory.get("/")
        google_sociallogin.user.name = "Already Set"
        data = {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com"}

        user = adapter.populate_user(request, google_sociallogin, data)

        assert user.name == "Already Set"

    def test_handles_first_name_only(self, adapter, google_sociallogin, request_factory):
        request = request_factory.get("/")
        data = {"first_name": "Jane", "last_name": "", "email": "jane@example.com"}

        user = adapter.populate_user(request, google_sociallogin, data)

        assert user.name == "Jane"

    def test_handles_empty_name_data(self, adapter, google_sociallogin, request_factory):
        request = request_factory.get("/")
        data = {"email": "jane@example.com"}

        user = adapter.populate_user(request, google_sociallogin, data)

        assert user.name == ""


@pytest.mark.django_db
class TestSyncOAuthConnection:
    def test_creates_oauth_connection(self, adapter, user, google_sociallogin):
        adapter._sync_oauth_connection(user, google_sociallogin)

        conn = OAuthConnection.objects.get(provider="google", provider_user_id="google-uid-123")
        assert conn.user == user

    def test_is_idempotent(self, adapter, user, google_sociallogin):
        adapter._sync_oauth_connection(user, google_sociallogin)
        adapter._sync_oauth_connection(user, google_sociallogin)

        assert OAuthConnection.objects.filter(provider="google", provider_user_id="google-uid-123").count() == 1

    def test_stores_provider_email(self, adapter, user):
        from allauth.account.models import EmailAddress

        account = AllAuthSocialAccount(provider="google", uid="google-uid-456")
        sociallogin = SocialLogin(
            user=user,
            account=account,
            email_addresses=[EmailAddress(email="google@example.com", verified=True, primary=True)],
        )

        adapter._sync_oauth_connection(user, sociallogin)

        conn = OAuthConnection.objects.get(provider_user_id="google-uid-456")
        assert conn.provider_email == "google@example.com"

    def test_ignores_non_google_provider(self, adapter, user):
        account = AllAuthSocialAccount(provider="github", uid="github-uid-789")
        sociallogin = SocialLogin(user=user, account=account)

        adapter._sync_oauth_connection(user, sociallogin)

        assert not OAuthConnection.objects.exists()

    def test_pre_social_login_syncs_for_existing_user(self, adapter, user, google_sociallogin, request_factory):
        request = request_factory.get("/")
        # user is already saved to DB, so sociallogin.is_existing is True
        assert google_sociallogin.is_existing

        adapter.pre_social_login(request, google_sociallogin)

        assert OAuthConnection.objects.filter(provider="google", provider_user_id="google-uid-123").exists()

    def test_pre_social_login_skips_new_user(self, adapter, request_factory):
        request = request_factory.get("/")
        # Unsaved user makes sociallogin.is_existing False
        account = AllAuthSocialAccount(provider="google", uid="google-uid-new")
        sociallogin = SocialLogin(user=User(), account=account)
        assert not sociallogin.is_existing

        adapter.pre_social_login(request, sociallogin)

        assert not OAuthConnection.objects.exists()
