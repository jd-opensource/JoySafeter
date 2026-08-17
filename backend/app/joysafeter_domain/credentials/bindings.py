from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar

from .types import (
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    CredentialUsage,
    NormalizedEndpoint,
    NormalizedMcpUrl,
    ProjectId,
    require_identifier,
    require_project_id,
)

_HTTP_TOKEN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")


class EngineKind(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    NATIVE = "native"
    PI = "pi"


class WebhookAuthMethod(StrEnum):
    HMAC = "hmac"
    BEARER = "bearer"


class EgressInjectKind(StrEnum):
    BEARER = "bearer"
    API_KEY = "api_key"
    RAW_HEADER = "raw_header"
    COOKIE = "cookie"


@dataclass(frozen=True, slots=True)
class ModelCatalogContext:
    provider_id: str
    protocol_id: str
    engine_kind: EngineKind
    model_ids: frozenset[str] | None

    def __post_init__(self) -> None:
        provider_id = self.provider_id.strip() if isinstance(self.provider_id, str) else self.provider_id
        protocol_id = self.protocol_id.strip() if isinstance(self.protocol_id, str) else self.protocol_id
        if not provider_id or not isinstance(provider_id, str):
            raise ValueError("Catalog provider id must not be blank")
        if not protocol_id or not isinstance(protocol_id, str):
            raise ValueError("Catalog protocol id must not be blank")
        if not isinstance(self.engine_kind, EngineKind):
            raise TypeError("Catalog engine kind must be an EngineKind")
        model_ids = self.model_ids
        if model_ids is not None:
            if isinstance(model_ids, (str, bytes, bytearray)) or not isinstance(model_ids, Iterable):
                raise TypeError("Catalog model ids must be a non-string iterable")
            normalized_model_ids: set[str] = set()
            for model_id in model_ids:
                if not isinstance(model_id, str):
                    raise TypeError("Catalog model ids must contain strings")
                normalized_model_id = model_id.strip()
                if not normalized_model_id:
                    raise ValueError("Catalog model ids must not contain blanks")
                normalized_model_ids.add(normalized_model_id)
            model_ids = frozenset(normalized_model_ids)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "protocol_id", protocol_id)
        object.__setattr__(self, "model_ids", model_ids)


@dataclass(frozen=True, slots=True)
class EgressInjectPolicy:
    kind: EgressInjectKind
    credential_field: CredentialFieldName
    header: str | None = None
    cookie_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EgressInjectKind):
            raise TypeError("egress inject kind must be an EgressInjectKind")
        if not isinstance(self.credential_field, CredentialFieldName):
            raise TypeError("egress inject credential field must be a CredentialFieldName")
        if self.header is not None and not isinstance(self.header, str):
            raise TypeError("egress inject header must be a string")
        if self.cookie_name is not None and not isinstance(self.cookie_name, str):
            raise TypeError("egress inject cookie name must be a string")
        header = self.header
        cookie_name = self.cookie_name
        if header is not None and not _HTTP_TOKEN.fullmatch(header):
            raise ValueError("egress inject header must be a single HTTP header name")
        if self.kind in {EgressInjectKind.API_KEY, EgressInjectKind.RAW_HEADER} and not header:
            raise ValueError(f"{self.kind.value} injection requires a header")
        if self.kind is EgressInjectKind.BEARER and header is not None:
            raise ValueError("bearer injection does not accept a header override")
        if self.kind is EgressInjectKind.COOKIE:
            if header is not None:
                raise ValueError("cookie injection does not accept a header")
            if not cookie_name or _HTTP_TOKEN.fullmatch(cookie_name) is None:
                raise ValueError("cookie injection requires a valid cookie name")
        elif cookie_name is not None:
            raise ValueError("cookie name is only valid for cookie injection")
        object.__setattr__(self, "header", header)
        object.__setattr__(self, "cookie_name", cookie_name)


@dataclass(frozen=True, slots=True)
class ModelInferenceBinding:
    usage: ClassVar[CredentialUsage] = CredentialUsage.MODEL_INFERENCE
    project_id: ProjectId
    credential_id: CredentialId
    engine_kind: EngineKind
    model_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        require_identifier(self.credential_id, label="credential id")
        if not isinstance(self.engine_kind, EngineKind):
            raise TypeError("model inference engine kind must be an EngineKind")
        if self.model_id is not None:
            normalized = self.model_id.strip()
            if not normalized:
                raise ValueError("model id must not be blank")
            object.__setattr__(self, "model_id", normalized)


@dataclass(frozen=True, slots=True)
class WebhookAuthBinding:
    usage: ClassVar[CredentialUsage] = CredentialUsage.WEBHOOK_AUTH
    project_id: ProjectId
    credential_id: CredentialId
    credential_field: CredentialFieldName
    methods: frozenset[WebhookAuthMethod]

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        require_identifier(self.credential_id, label="credential id")
        if not isinstance(self.credential_field, CredentialFieldName):
            raise TypeError("webhook credential field must be a CredentialFieldName")
        methods = frozenset(self.methods)
        if not methods or any(not isinstance(method, WebhookAuthMethod) for method in methods):
            raise ValueError("webhook auth methods must contain supported values")
        object.__setattr__(self, "methods", methods)


@dataclass(frozen=True, slots=True)
class EnvironmentInjectionBinding:
    usage: ClassVar[CredentialUsage] = CredentialUsage.ENVIRONMENT_INJECTION
    project_id: ProjectId
    credential_id: CredentialId

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        require_identifier(self.credential_id, label="credential id")


@dataclass(frozen=True, slots=True)
class HttpEgressBinding:
    usage: ClassVar[CredentialUsage] = CredentialUsage.HTTP_EGRESS
    project_id: ProjectId
    credential_id: CredentialId
    endpoint: NormalizedEndpoint
    inject: EgressInjectPolicy

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        require_identifier(self.credential_id, label="credential id")
        if not isinstance(self.endpoint, NormalizedEndpoint):
            raise TypeError("HTTP egress endpoint must be normalized")
        if not isinstance(self.inject, EgressInjectPolicy):
            raise TypeError("HTTP egress inject policy is required")


@dataclass(frozen=True, slots=True)
class McpGroupBinding:
    usage: ClassVar[CredentialUsage] = CredentialUsage.MCP_EGRESS
    project_id: ProjectId
    group_ids: tuple[CredentialGroupId, ...]
    declared_server_urls: tuple[NormalizedMcpUrl, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        group_ids = tuple(self.group_ids)
        if not group_ids:
            raise ValueError("MCP Group binding requires at least one group id")
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("MCP Group binding contains duplicate group ids")
        for group_id in group_ids:
            require_identifier(group_id, label="credential group id")
        urls = tuple(self.declared_server_urls)
        if any(not isinstance(url, NormalizedMcpUrl) for url in urls):
            raise TypeError("MCP Group declared server URLs must be normalized")
        if len(set(urls)) != len(urls):
            raise ValueError("MCP Group binding contains duplicate declared server URLs")
        object.__setattr__(self, "group_ids", group_ids)
        object.__setattr__(self, "declared_server_urls", urls)


CredentialBinding = (
    ModelInferenceBinding | WebhookAuthBinding | EnvironmentInjectionBinding | HttpEgressBinding | McpGroupBinding
)
