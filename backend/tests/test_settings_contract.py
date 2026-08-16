import pytest
from pydantic import ValidationError

from app.joysafeter_shared.config.settings import Settings

pytestmark = pytest.mark.no_db


def test_settings_accept_only_canonical_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("DEBUG", raising=False)
    monkeypatch.setenv("APP_DEBUG", "true")
    monkeypatch.setenv("JWT_SECRET_KEY", "removed-alias")

    settings = Settings(_env_file=None)

    assert settings.debug is False
    assert settings.secret_key == "test-secret"


def test_removed_secret_key_alias_is_rejected(monkeypatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "removed-alias")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_identity_federation_settings_use_only_canonical_environment_names(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("IDENTITY_FEDERATION_PROVIDERS", "jd,github")
    monkeypatch.setenv("IDENTITY_FEDERATION_CONFIG_PATH", "/run/config/federation.yaml")
    monkeypatch.setenv("IDENTITY_FEDERATION_LOGIN_MODE", "redirect")
    monkeypatch.setenv("OAUTH_CONFIG_PATH", "/run/config/legacy-oauth.yaml")

    settings = Settings(_env_file=None)

    assert settings.identity_federation_providers == "jd,github"
    assert settings.identity_federation_config_path == "/run/config/federation.yaml"
    assert settings.identity_federation_login_mode == "redirect"
    assert "oauth_config_path" not in Settings.model_fields
    assert not hasattr(settings, "oauth_config_path")


def test_identity_federation_settings_ignore_removed_legacy_oauth_environment(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("IDENTITY_FEDERATION_PROVIDERS", raising=False)
    monkeypatch.delenv("IDENTITY_FEDERATION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("IDENTITY_FEDERATION_LOGIN_MODE", raising=False)
    monkeypatch.setenv("OAUTH_CONFIG_PATH", "/run/config/legacy-oauth.yaml")

    settings = Settings(_env_file=None)

    assert "oauth_config_path" not in Settings.model_fields
    assert not hasattr(settings, "oauth_config_path")
    assert settings.identity_federation_providers == ""
    assert settings.identity_federation_config_path is None
    assert settings.identity_federation_login_mode == "chooser"


def test_identity_federation_settings_default_to_no_active_providers(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("IDENTITY_FEDERATION_PROVIDERS", raising=False)
    monkeypatch.delenv("IDENTITY_FEDERATION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("IDENTITY_FEDERATION_LOGIN_MODE", raising=False)

    settings = Settings(_env_file=None)

    assert settings.identity_federation_providers == ""
    assert settings.identity_federation_config_path is None
    assert settings.identity_federation_login_mode == "chooser"


def test_backend_url_defaults_to_local_api_origin(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("BACKEND_URL", raising=False)

    settings = Settings(_env_file=None)

    assert settings.backend_url == "http://localhost:8000"


def test_backend_url_accepts_and_normalizes_public_http_origin(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com:8443/")

    settings = Settings(_env_file=None)

    assert settings.backend_url == "https://api.example.com:8443"


@pytest.mark.parametrize(
    "backend_url",
    [
        "api.example.com",
        "ftp://api.example.com",
        "https://user:pass@api.example.com",
        "https://api.example.com/base-path",
        "https://api.example.com?query=1",
        "https://api.example.com#fragment",
    ],
)
def test_backend_url_rejects_non_origin_values(monkeypatch, backend_url: str) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("BACKEND_URL", backend_url)

    with pytest.raises(ValueError, match="BACKEND_URL"):
        Settings(_env_file=None)
