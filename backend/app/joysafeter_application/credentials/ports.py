from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    CredentialImpact,
    ReferenceScannerId,
)
from app.joysafeter_domain.credentials.resource import CredentialGroupResource, CredentialResource
from app.joysafeter_domain.credentials.types import CredentialFieldName, CredentialId, ProjectId

if TYPE_CHECKING:
    from .binding_service import ResolvedCredentialMaterial, ValidatedCredentialBinding


@dataclass(frozen=True, slots=True)
class CredentialAuditEntry:
    action: str
    project_id: str
    target_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


class CredentialRepositoryPort(Protocol):
    async def create(self, request: Any, project_id: str) -> Any: ...

    async def get(self, credential_id: Any, project_id: str) -> Any | None: ...

    async def get_resource(
        self,
        credential_id: CredentialId,
        project_id: ProjectId,
    ) -> CredentialResource | None: ...

    async def load_encrypted_material(
        self,
        credential_id: CredentialId,
        project_id: ProjectId,
    ) -> Mapping[str, str]: ...

    def take_pending_impacts(self) -> tuple[CredentialImpact, ...]: ...

    def clear_pending_impacts(self) -> None: ...


class CredentialGroupRepositoryPort(Protocol):
    async def get_group(
        self,
        group_id: Any,
        project_id: str,
    ) -> CredentialGroupResource | None: ...

    async def get_many(
        self,
        group_ids: tuple[Any, ...],
        project_id: str,
    ) -> tuple[CredentialGroupResource, ...]: ...

    async def list_members(
        self,
        group_ids: tuple[Any, ...],
        project_id: str,
    ) -> tuple[CredentialResource, ...]: ...


class CredentialMaterialPort(Protocol):
    async def load(self, binding: ValidatedCredentialBinding) -> ResolvedCredentialMaterial: ...


class CredentialAuditPort(Protocol):
    async def append(self, entry: CredentialAuditEntry) -> None: ...


class CredentialImpactPort(Protocol):
    async def mark_pending(self, impact: CredentialImpact) -> CredentialImpact: ...

    async def nudge_after_commit(self) -> None: ...


class ReferenceScanner(Protocol):
    scanner_id: ReferenceScannerId

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> Sequence[CredentialDependency]: ...


class CredentialUnitOfWork(Protocol):
    credentials: CredentialRepositoryPort
    groups: CredentialGroupRepositoryPort
    audit: CredentialAuditPort
    impacts: CredentialImpactPort

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class EncryptedCredentialMaterialRepositoryPort(Protocol):
    async def load_encrypted_material(
        self,
        credential_id: CredentialId,
        project_id: ProjectId,
    ) -> Mapping[str, str]: ...


class CredentialMaterialStoragePort(Protocol):
    def protect_values(self, values: Mapping[str, str] | None) -> dict[str, str]: ...

    def reveal_values(self, values: Mapping[str, str] | None) -> dict[str, str]: ...


AuthorizedCredentialFields = frozenset[CredentialFieldName]
