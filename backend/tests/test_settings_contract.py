import json
from pathlib import Path

import pytest
import yaml
from dotenv import dotenv_values
from pydantic import ValidationError

from app.joysafeter_shared.config.settings import Settings

pytestmark = pytest.mark.no_db

REPO_ROOT = Path(__file__).resolve().parents[2]


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


def test_frontend_url_accepts_and_normalizes_public_https_origin(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("FRONTEND_URL", "https://App.Example.com:8443/")

    settings = Settings(_env_file=None)

    assert settings.frontend_url == "https://app.example.com:8443"


@pytest.mark.parametrize(
    "frontend_url",
    [
        "app.example.com",
        "ftp://app.example.com",
        "https://user:pass@app.example.com",
        "https://app.example.com/base-path",
        "https://app.example.com?query=1",
        "https://app.example.com#fragment",
    ],
)
def test_frontend_url_rejects_non_origin_values(monkeypatch, frontend_url: str) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("FRONTEND_URL", frontend_url)

    with pytest.raises(ValueError, match="FRONTEND_URL"):
        Settings(_env_file=None)


def test_production_rejects_public_http_backend_url(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BACKEND_URL", "http://api.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    with pytest.raises(
        ValidationError,
        match=r"BACKEND_URL must use https:// in production.*Secure federation/auth cookies",
    ):
        Settings(_env_file=None)


def test_production_rejects_public_http_frontend_url(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")
    monkeypatch.setenv("FRONTEND_URL", "http://app.example.com")

    with pytest.raises(
        ValidationError,
        match=r"FRONTEND_URL must use https:// in production.*redirects and email links",
    ):
        Settings(_env_file=None)


@pytest.mark.parametrize("setting_name", ["BACKEND_URL", "FRONTEND_URL"])
def test_production_rejects_loopback_http_public_origins(monkeypatch, setting_name: str) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv(setting_name, "http://127.0.0.1:8000")

    with pytest.raises(ValidationError, match=rf"{setting_name} must use https:// in production"):
        Settings(_env_file=None)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_non_production_allows_loopback_http_public_origins(monkeypatch, environment: str) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("BACKEND_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:3000")

    settings = Settings(_env_file=None)

    assert settings.backend_url == "http://127.0.0.1:8000"
    assert settings.frontend_url == "http://localhost:3000"


def test_remote_example_uses_https_public_origin_contract(monkeypatch) -> None:
    values = dotenv_values(REPO_ROOT / "deploy/.env.remote.example")

    assert values["ENVIRONMENT"] == "production"
    assert values["FRONTEND_URL"] == "https://joysafeter-pre.jd.com"
    assert values["BACKEND_URL"] == "https://joysafeter-api-pre.jd.com"
    assert json.loads(values["CORS_ORIGINS"] or "null") == ["https://joysafeter-pre.jd.com"]
    assert json.loads(values["BACKEND_CORS_ORIGINS"] or "null") == ["https://joysafeter-pre.jd.com"]
    assert values["NEXT_PUBLIC_CSP_CONNECT_SRC_EXTRA"] == "https://joysafeter-api-pre.jd.com"

    monkeypatch.setenv("SECRET_KEY", "test-secret")
    for setting_name in ("ENVIRONMENT", "FRONTEND_URL", "BACKEND_URL", "CORS_ORIGINS"):
        monkeypatch.setenv(setting_name, values[setting_name] or "")

    settings = Settings(_env_file=None)

    assert settings.frontend_url == values["FRONTEND_URL"]
    assert settings.backend_url == values["BACKEND_URL"]
    assert settings.cors_origins == [values["FRONTEND_URL"]]


def test_compose_passes_public_origins_to_backend_services() -> None:
    compose = yaml.safe_load((REPO_ROOT / "deploy/docker-compose.yml").read_text(encoding="utf-8"))
    common_environment = compose["x-backend-common-env"]

    assert common_environment["ENVIRONMENT"] == "${ENVIRONMENT:-development}"
    assert common_environment["BACKEND_URL"] == "${BACKEND_URL:-http://localhost:8000}"
    assert common_environment["FRONTEND_URL"] == "${FRONTEND_URL:-http://localhost:3000}"


def test_cookie_secure_effective_remains_forced_on_in_production(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("BACKEND_URL", "https://api.example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")
    monkeypatch.setenv("COOKIE_SECURE", "false")

    settings = Settings(_env_file=None)

    assert settings.cookie_secure_effective is True


@pytest.mark.parametrize(("cookie_secure", "expected"), [("true", True), ("false", False)])
def test_cookie_secure_effective_remains_configurable_outside_production(
    monkeypatch,
    cookie_secure: str,
    expected: bool,
) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("COOKIE_SECURE", cookie_secure)

    settings = Settings(_env_file=None)

    assert settings.cookie_secure_effective is expected
