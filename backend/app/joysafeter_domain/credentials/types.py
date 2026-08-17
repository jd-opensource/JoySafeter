from __future__ import annotations

from enum import StrEnum
from typing import NewType
from urllib.parse import SplitResult, urlsplit, urlunsplit

CREDENTIAL_FIELD_NAME_MAX_LENGTH = 128

ProjectId = NewType("ProjectId", str)
CredentialId = NewType("CredentialId", str)
CredentialGroupId = NewType("CredentialGroupId", str)


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
        return str.__new__(cls, _normalize_http_url(value, label="MCP URL"))


def make_project_id(value: str) -> ProjectId:
    if not isinstance(value, str):
        raise TypeError("project id must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("project id must not be blank")
    return ProjectId(normalized)


def canonicalize_auth_scheme(value: str | CredentialAuthScheme) -> CredentialAuthScheme:
    if isinstance(value, CredentialAuthScheme):
        return value
    if not isinstance(value, str):
        raise TypeError("credential auth scheme must be a string")
    if value in {"static_bearer", "bearer"}:
        return CredentialAuthScheme.STATIC_BEARER
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
    return make_project_id(value)


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
