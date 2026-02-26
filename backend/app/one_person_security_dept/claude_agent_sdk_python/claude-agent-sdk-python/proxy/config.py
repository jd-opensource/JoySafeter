"""Configuration handling for the OpenAI -> Anthropic proxy."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any


class SettingsError(ValueError):
    """Raised when proxy settings are invalid."""


@dataclass(frozen=True)
class ProxySettings:
    """Runtime settings for the proxy service."""

    openai_base_url: str
    model_map: dict[str, str] = field(default_factory=dict)
    fallback_models: list[dict[str, Any]] = field(default_factory=list)
    default_max_tokens: int = 4096
    upstream_timeout_seconds: float = 90.0
    upstream_extra_headers: dict[str, str] = field(default_factory=dict)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "ProxySettings":
        """Create settings from environment variables."""
        openai_base_url = os.getenv("OPENAI_BASE_URL", "").strip()
        if not openai_base_url:
            raise SettingsError("OPENAI_BASE_URL is required")

        model_map = _parse_json_mapping(
            os.getenv("MODEL_MAP_JSON", ""),
            "MODEL_MAP_JSON",
            value_type=str,
        )
        fallback_models = _parse_fallback_models(os.getenv("FALLBACK_MODELS_JSON", ""))
        upstream_extra_headers = _parse_json_mapping(
            os.getenv("UPSTREAM_EXTRA_HEADERS_JSON", ""),
            "UPSTREAM_EXTRA_HEADERS_JSON",
            value_type=str,
        )

        default_max_tokens = _parse_int(os.getenv("DEFAULT_MAX_TOKENS"), 4096, "DEFAULT_MAX_TOKENS")
        upstream_timeout_seconds = _parse_float(
            os.getenv("UPSTREAM_TIMEOUT_SECONDS"),
            90.0,
            "UPSTREAM_TIMEOUT_SECONDS",
        )
        log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"

        return cls(
            openai_base_url=openai_base_url,
            model_map=model_map,
            fallback_models=fallback_models,
            default_max_tokens=default_max_tokens,
            upstream_timeout_seconds=upstream_timeout_seconds,
            upstream_extra_headers=upstream_extra_headers,
            log_level=log_level,
        )


def _parse_json_mapping(
    raw: str,
    env_name: str,
    *,
    value_type: type,
) -> dict[str, Any]:
    """Parse a JSON object env var into a string-key mapping."""
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SettingsError(f"{env_name} must be valid JSON object") from exc

    if not isinstance(parsed, dict):
        raise SettingsError(f"{env_name} must be a JSON object")

    result: dict[str, Any] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            raise SettingsError(f"{env_name} keys must be strings")
        if not isinstance(value, value_type):
            typename = value_type.__name__
            raise SettingsError(f"{env_name} values must be {typename}")
        result[key] = value

    return result


def _parse_fallback_models(raw: str) -> list[dict[str, Any]]:
    """Parse FALLBACK_MODELS_JSON into normalized model objects."""
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SettingsError("FALLBACK_MODELS_JSON must be valid JSON array") from exc

    if not isinstance(parsed, list):
        raise SettingsError("FALLBACK_MODELS_JSON must be a JSON array")

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(parsed):
        if isinstance(item, str):
            model_id = item.strip()
            if not model_id:
                raise SettingsError(f"FALLBACK_MODELS_JSON[{idx}] must be non-empty string")
            normalized.append(
                {
                    "id": model_id,
                    "type": "model",
                    "display_name": model_id,
                }
            )
            continue

        if not isinstance(item, dict):
            raise SettingsError(f"FALLBACK_MODELS_JSON[{idx}] must be string or object")

        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            raise SettingsError(f"FALLBACK_MODELS_JSON[{idx}].id must be a non-empty string")
        model_id = model_id.strip()

        converted: dict[str, Any] = {
            "id": model_id,
            "type": "model",
            "display_name": item.get("display_name", model_id),
        }

        created_at = item.get("created_at")
        if created_at is not None:
            converted["created_at"] = created_at

        normalized.append(converted)

    return normalized


def _parse_int(raw: str | None, default: int, env_name: str) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SettingsError(f"{env_name} must be an integer") from exc
    if value <= 0:
        raise SettingsError(f"{env_name} must be positive")
    return value


def _parse_float(raw: str | None, default: float, env_name: str) -> float:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SettingsError(f"{env_name} must be a number") from exc
    if value <= 0:
        raise SettingsError(f"{env_name} must be positive")
    return value


def build_openai_url(base_url: str, endpoint: str) -> str:
    """Build an OpenAI endpoint URL from base url and endpoint suffix."""
    normalized = base_url.rstrip("/")
    suffix = endpoint.lstrip("/")
    if normalized.endswith("/v1"):
        return f"{normalized}/{suffix}"
    return f"{normalized}/v1/{suffix}"
