from datetime import datetime, timedelta, timezone

import pytest

from app.joysafeter_identity_federation.domain.errors import (
    ConfigurationIssue,
    FederationConfigurationError,
    FederationError,
)
from app.joysafeter_identity_federation.domain.models import (
    CorrelationMethod,
    FederatedPrincipal,
    JDSSOProviderSettings,
    LoginAttempt,
    OAuth2ProviderSettings,
    ProviderId,
)
from app.joysafeter_identity_federation.domain.policies import AccountLinkPolicy

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("raw", ["", "JD", "jd sso", "jd/sso", "-jd"])
def test_provider_id_rejects_non_canonical_values(raw: str) -> None:
    with pytest.raises(ValueError):
        ProviderId(raw)


def test_login_attempt_is_expired_at_boundary() -> None:
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    attempt = LoginAttempt(
        id="attempt-1",
        provider_id=ProviderId("jd"),
        callback_url="/managed/quickstart",
        redirect_uri="https://api.example.com/api/v1/auth/oauth/jd/callback",
        correlation_method=CorrelationMethod.SIGNED_COOKIE,
        retry_count=0,
        created_at=now - timedelta(seconds=600),
        expires_at=now,
    )

    assert attempt.is_expired(now) is True


def test_federated_principal_requires_stable_subject() -> None:
    with pytest.raises(ValueError):
        FederatedPrincipal(
            provider_id=ProviderId("github"),
            subject="",
            email="user@example.com",
            email_verified=True,
            display_name="User",
            avatar_url=None,
            claims={},
        )


def test_federated_principal_normalizes_email_and_freezes_claims() -> None:
    claims = {"sub": "123"}
    principal = FederatedPrincipal(
        provider_id=ProviderId("github"),
        subject="123",
        email=" User@Example.COM ",
        email_verified=True,
        display_name="User",
        avatar_url=None,
        claims=claims,
    )

    assert principal.email == "user@example.com"
    claims["role"] = "admin"
    assert "role" not in principal.claims
    with pytest.raises(TypeError):
        principal.claims["sub"] = "456"


def test_provider_settings_freeze_mapping_fields() -> None:
    user_mapping = {"subject": "sub"}
    headers = {"Accept": "application/json"}
    oauth_settings = OAuth2ProviderSettings(
        client_id="client",
        client_secret="secret",
        authorize_url=None,
        token_url=None,
        userinfo_url=None,
        issuer=None,
        scope="openid",
        user_mapping=user_mapping,
        userinfo_headers=headers,
    )
    jd_settings = JDSSOProviderSettings(
        client_id="client",
        client_secret="secret",
        authorize_url="https://id.example.com/authorize",
        userinfo_url="https://id.example.com/userinfo",
        scope="openid",
        user_mapping=user_mapping,
    )

    user_mapping["email"] = "email"
    headers["X-Test"] = "value"
    assert "email" not in oauth_settings.user_mapping
    assert "X-Test" not in oauth_settings.userinfo_headers
    assert "email" not in jd_settings.user_mapping
    with pytest.raises(TypeError):
        oauth_settings.user_mapping["subject"] = "changed"


def test_configuration_error_renders_all_issues_in_order() -> None:
    error = FederationConfigurationError(
        [
            ConfigurationIssue("jd", "client_id", "FEDERATION_ENV_UNRESOLVED", "JD_CLIENT_ID is unset"),
            ConfigurationIssue("jd", "userinfo_url", "FEDERATION_PROVIDER_CONFIG_INVALID", "URL is invalid"),
        ]
    )

    assert [issue.field for issue in error.issues] == ["client_id", "userinfo_url"]
    assert "FEDERATION_ENV_UNRESOLVED" in str(error)


def test_auto_link_rejects_unverified_external_email() -> None:
    policy = AccountLinkPolicy(allow_registration=True, auto_link_by_email=True)

    with pytest.raises(FederationError) as exc_info:
        policy.require_auto_link_allowed(
            principal_email="user@example.com",
            principal_email_verified=False,
            existing_user_email="user@example.com",
            existing_user_active=True,
        )

    assert exc_info.value.code == "FEDERATION_ACCOUNT_LINK_REQUIRED"


def test_auto_link_accepts_verified_exact_normalized_email() -> None:
    policy = AccountLinkPolicy(allow_registration=True, auto_link_by_email=True)

    policy.require_auto_link_allowed(
        principal_email=" User@Example.com ",
        principal_email_verified=True,
        existing_user_email="user@example.com",
        existing_user_active=True,
    )
