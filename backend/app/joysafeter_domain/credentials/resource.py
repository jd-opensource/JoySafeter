from __future__ import annotations

import re
from dataclasses import dataclass

from .material import CREDENTIAL_MATERIAL_MAX_FIELDS
from .types import (
    CredentialAuthScheme,
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    CredentialKind,
    CredentialState,
    NormalizedMcpUrl,
    ProjectId,
    require_identifier,
    require_non_empty_text,
    require_project_id,
)

_POSIX_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ModelCredentialIdentity:
    provider_id: str
    protocol_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", require_non_empty_text(self.provider_id, label="provider id"))
        object.__setattr__(self, "protocol_id", require_non_empty_text(self.protocol_id, label="protocol id"))


@dataclass(frozen=True, slots=True)
class ServiceCredentialIdentity:
    auth_scheme: CredentialAuthScheme

    def __post_init__(self) -> None:
        if not isinstance(self.auth_scheme, CredentialAuthScheme):
            raise TypeError("service credential auth scheme must be a CredentialAuthScheme")


@dataclass(frozen=True, slots=True)
class McpCredentialIdentity:
    group_id: CredentialGroupId
    server_url: NormalizedMcpUrl
    auth_scheme: CredentialAuthScheme

    def __post_init__(self) -> None:
        require_identifier(self.group_id, label="credential group id")
        if not isinstance(self.server_url, NormalizedMcpUrl):
            raise TypeError("MCP server URL must be normalized")
        if not isinstance(self.auth_scheme, CredentialAuthScheme):
            raise TypeError("MCP credential auth scheme must be a CredentialAuthScheme")


CredentialIdentity = ModelCredentialIdentity | ServiceCredentialIdentity | McpCredentialIdentity


@dataclass(frozen=True, slots=True)
class CredentialMaterialDescriptor:
    field_names: frozenset[CredentialFieldName]

    def __post_init__(self) -> None:
        copied = frozenset(
            name if isinstance(name, CredentialFieldName) else CredentialFieldName(name) for name in self.field_names
        )
        if len(copied) > CREDENTIAL_MATERIAL_MAX_FIELDS:
            raise ValueError(f"credential material descriptor supports at most {CREDENTIAL_MATERIAL_MAX_FIELDS} fields")
        object.__setattr__(self, "field_names", copied)

    def require_field(self, field_name: CredentialFieldName) -> None:
        if field_name not in self.field_names:
            raise ValueError(f"credential material field is missing: {field_name}")

    def validate_environment_field_names(self) -> None:
        invalid = sorted(name for name in self.field_names if _POSIX_ENVIRONMENT_NAME.fullmatch(name) is None)
        if invalid:
            raise ValueError(f"Environment Injection requires POSIX field names: {', '.join(invalid)}")


@dataclass(frozen=True, slots=True)
class CredentialResource:
    id: CredentialId
    project_id: ProjectId
    name: str
    kind: CredentialKind
    identity: CredentialIdentity
    material: CredentialMaterialDescriptor
    state: CredentialState
    is_default: bool

    def __post_init__(self) -> None:
        require_identifier(self.id, label="credential id")
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        object.__setattr__(self, "name", require_non_empty_text(self.name, label="credential name"))
        if not isinstance(self.kind, CredentialKind):
            raise TypeError("credential kind must be a CredentialKind")
        if not isinstance(self.material, CredentialMaterialDescriptor):
            raise TypeError("credential resource must carry a material descriptor")
        if not isinstance(self.state, CredentialState):
            raise TypeError("credential state must be a CredentialState")
        expected_identity = {
            CredentialKind.MODEL: ModelCredentialIdentity,
            CredentialKind.SERVICE: ServiceCredentialIdentity,
            CredentialKind.MCP: McpCredentialIdentity,
        }[self.kind]
        if not isinstance(self.identity, expected_identity):
            raise TypeError(f"credential kind {self.kind.value} has an incompatible identity")
        if self.is_default and self.kind is not CredentialKind.MODEL:
            raise ValueError("only model credentials may be default")
        if self.is_default and self.state is not CredentialState.ACTIVE:
            raise ValueError("inactive model credentials cannot be default")


@dataclass(frozen=True, slots=True)
class CredentialGroupResource:
    id: CredentialGroupId
    project_id: ProjectId
    name: str
    state: CredentialState

    def __post_init__(self) -> None:
        require_identifier(self.id, label="credential group id")
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        object.__setattr__(self, "name", require_non_empty_text(self.name, label="credential group name"))
        if not isinstance(self.state, CredentialState):
            raise TypeError("credential group state must be a CredentialState")
