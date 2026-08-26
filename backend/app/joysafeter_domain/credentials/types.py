from __future__ import annotations

from enum import StrEnum
from urllib.parse import SplitResult, urlsplit, urlunsplit

from app.joysafeter_shared.ids import CredentialGroupId, CredentialId, ProjectId

CREDENTIAL_FIELD_NAME_MAX_LENGTH = 128


class CredentialKind(StrEnum):
    MODEL = "model"
    SERVICE = "service"
    MCP = "mcp"


class CredentialState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class CredentialAuthScheme(StrEnum):
    STATIC_BEARER = "static_bearer"
    HEADER_API_KEY = "header_api_key"
    CUSTOM_HEADER = "custom_header"
    OAUTH2_LEGACY_DISABLED = "oauth2_legacy_disabled"


class CredentialUsage(StrEnum):
    MODEL_INFERENCE = "model_inference"
    WEBHOOK_AUTH = "webhook_auth"
    ENVIRONMENT_INJECTION = "environment_injection"
    HTTP_EGRESS = "http_egress"
    MCP_EGRESS = "mcp_egress"


class CredentialFieldName(str):
    def __new__(cls, value: str) -> CredentialFieldName:
        if not isinstance(value, str):
            raise TypeError("credential field name must be a string")
        if not 1 <= len(value) <= CREDENTIAL_FIELD_NAME_MAX_LENGTH:
            raise ValueError(
                f"credential field name must contain 1-{CREDENTIAL_FIELD_NAME_MAX_LENGTH} Unicode characters"
            )
        return str.__new__(cls, value)


class NormalizedEndpoint(str):
    def __new__(cls, value: str) -> NormalizedEndpoint:
        return str.__new__(cls, _normalize_http_url(value, label="HTTP endpoint"))


class NormalizedMcpUrl(str):
    def __new__(cls, value: str) -> NormalizedMcpUrl:
        normalized = _normalize_http_url(value, label="MCP URL")
        if normalized.endswith("/"):
            normalized = normalized[:-1]
        return str.__new__(cls, normalized)


def require_credential_id(value: CredentialId) -> CredentialId:
    if type(value) is not CredentialId:
        raise TypeError("credential id must be a CredentialId")
    return value


def require_credential_group_id(value: CredentialGroupId) -> CredentialGroupId:
    if type(value) is not CredentialGroupId:
        raise TypeError("credential group id must be a CredentialGroupId")
    return value


def canonicalize_auth_scheme(value: str | CredentialAuthScheme) -> CredentialAuthScheme:
    if isinstance(value, CredentialAuthScheme):
        return value
    if not isinstance(value, str):
        raise TypeError("credential auth scheme must be a string")
    if value in {"static_bearer", "bearer"}:
        return CredentialAuthScheme.STATIC_BEARER
    if value in {"header_api_key", "api_key"}:
        return CredentialAuthScheme.HEADER_API_KEY
    if value == "custom_header":
        return CredentialAuthScheme.CUSTOM_HEADER
    if value in {"oauth", "mcp_oauth"}:
        return CredentialAuthScheme.OAUTH2_LEGACY_DISABLED
    raise ValueError(f"unsupported credential auth scheme: {value!r}")


def require_non_empty_text(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be blank")
    return normalized


def require_project_id(value: ProjectId) -> ProjectId:
    if type(value) is not ProjectId:
        raise TypeError("project id must be a ProjectId")
    return value


def require_identifier(value: str, *, label: str) -> str:
    return require_non_empty_text(value, label=label)


def _normalize_http_url(value: str, *, label: str) -> str:
    raw = require_non_empty_text(value, label=label)
    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(f"{label} must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{label} must not contain user information")
    if parsed.fragment:
        raise ValueError(f"{label} must not contain a fragment")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"{label} must contain a host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{label} contains an invalid port") from exc
    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    default_port = (parsed.scheme.lower() == "http" and port == 80) or (
        parsed.scheme.lower() == "https" and port == 443
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    normalized = SplitResult(
        scheme=parsed.scheme.lower(),
        netloc=netloc,
        path=parsed.path or "",
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)
