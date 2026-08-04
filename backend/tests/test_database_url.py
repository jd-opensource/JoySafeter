import pytest

from app.joysafeter_shared.database_url import database_url_from_env, database_url_sync_from_env

pytestmark = pytest.mark.no_db


def test_database_url_uses_remote_postgres_environment(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_HOST", "postgres.internal")
    monkeypatch.setenv("POSTGRES_PORT", "5544")
    monkeypatch.setenv("POSTGRES_PORT_HOST", "9999")
    monkeypatch.setenv("POSTGRES_USER", "joysafeter")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "control")

    assert database_url_from_env() == "postgresql+asyncpg://joysafeter:secret@postgres.internal:5544/control"
    assert database_url_sync_from_env() == "postgresql://joysafeter:secret@postgres.internal:5544/control"
