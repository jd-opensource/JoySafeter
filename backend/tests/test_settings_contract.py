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
    assert settings.oauth_config_path == "/run/config/legacy-oauth.yaml"


def test_identity_federation_settings_do_not_fall_back_to_legacy_oauth(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.delenv("IDENTITY_FEDERATION_PROVIDERS", raising=False)
    monkeypatch.delenv("IDENTITY_FEDERATION_CONFIG_PATH", raising=False)
    monkeypatch.delenv("IDENTITY_FEDERATION_LOGIN_MODE", raising=False)
    monkeypatch.setenv("OAUTH_CONFIG_PATH", "/run/config/legacy-oauth.yaml")

    settings = Settings(_env_file=None)

    assert settings.oauth_config_path == "/run/config/legacy-oauth.yaml"
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
