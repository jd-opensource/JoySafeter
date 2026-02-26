from __future__ import annotations

from proxy.config import ProxySettings, SettingsError


def test_fallback_models_json_parses_string_and_object(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com")
    monkeypatch.setenv(
        "FALLBACK_MODELS_JSON",
        '["Kimi-K2.5", {"id": "Kimi-Vision", "display_name": "Kimi Vision"}]',
    )

    settings = ProxySettings.from_env()

    assert settings.fallback_models == [
        {"id": "Kimi-K2.5", "type": "model", "display_name": "Kimi-K2.5"},
        {"id": "Kimi-Vision", "type": "model", "display_name": "Kimi Vision"},
    ]


def test_fallback_models_json_requires_array(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com")
    monkeypatch.setenv("FALLBACK_MODELS_JSON", '{"id": "Kimi-K2.5"}')

    try:
        ProxySettings.from_env()
    except SettingsError as exc:
        assert "FALLBACK_MODELS_JSON must be a JSON array" in str(exc)
    else:
        raise AssertionError("Expected SettingsError")
