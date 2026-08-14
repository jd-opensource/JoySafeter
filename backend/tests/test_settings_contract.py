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
