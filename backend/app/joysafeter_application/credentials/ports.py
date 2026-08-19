from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    CredentialImpact,
    ReferenceScannerId,
)
from app.joysafeter_domain.credentials.resource import CredentialGroupResource, CredentialResource
from app.joysafeter_domain.credentials.types import (
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    ProjectId,
)

if TYPE_CHECKING:
    from .binding_service import ResolvedCredentialMaterial, ValidatedCredentialBinding

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MutationOutcome(Generic[T]):
    value: T
    changed: bool


@dataclass(frozen=True, slots=True)
class CredentialAuditEntry:
    action: str
    project_id: str | None
    target_type: str = "credential"
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

    async def lock_credentials(
        self,
        credential_ids: Sequence[object],
        *,
        project_id: str | None = None,
    ) -> Sequence[object]: ...

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

    async def lock_credential_groups(
        self,
        group_ids: Sequence[object],
        *,
        project_id: str | None = None,
    ) -> Sequence[object]: ...


@dataclass(frozen=True, slots=True)
class CredentialSnapshotSource:
    agent_id: object
    agent_name: str
    agent_version: int
    snapshot: Mapping[str, Any]
    environment_ref: str | None
    source_version_id: object | None
    environment_id: object | None


@dataclass(frozen=True, slots=True)
class CredentialSnapshotSession:
    agent_id: object
    project_id: str | None
    title: str
    metadata: Mapping[str, object]
    credential_group_ids: tuple[object, ...]
    environment_ref: str | None
    agent_version: int
    agent_snapshot: Mapping[str, Any]


class CredentialSnapshotSourcePort(Protocol):
    async def load(
        self,
        command: object,
        *,
        for_update: bool = False,
    ) -> CredentialSnapshotSource: ...


class CredentialSessionRepositoryPort(Protocol):
    async def create(self, request: CredentialSnapshotSession) -> Any: ...

    async def refresh(self, session: Any) -> None: ...


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

    async def scan_group(
        self,
        project_id: ProjectId,
        group_id: CredentialGroupId,
    ) -> Sequence[CredentialDependency]: ...


class CredentialUnitOfWork(Protocol):
    credentials: CredentialRepositoryPort
    groups: CredentialGroupRepositoryPort
    audit: CredentialAuditPort
    impacts: CredentialImpactPort
    sources: CredentialSnapshotSourcePort
    sessions: CredentialSessionRepositoryPort

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
