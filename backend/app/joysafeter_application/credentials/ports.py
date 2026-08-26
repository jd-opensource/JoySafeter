from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    CredentialImpact,
    CredentialUsage,
    ReferenceScannerId,
)
from app.joysafeter_domain.credentials.resource import CredentialGroupResource, CredentialResource
from app.joysafeter_domain.credentials.types import (
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    ProjectId,
)
from app.joysafeter_shared.ids import (
    AgentId,
    AgentVersionId,
    CredentialAccessAuditId,
    EnvironmentId,
    OrganizationId,
    SecurityAuditId,
    SessionId,
    TaskId,
    UserId,
)

if TYPE_CHECKING:
    from .binding_service import ResolvedCredentialMaterial, ValidatedCredentialBinding

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class MutationOutcome(Generic[T]):
    value: T
    changed: bool


def combine_credential_impacts(
    impacts: Sequence[CredentialImpact],
) -> CredentialImpact | None:
    if not impacts:
        return None
    first = impacts[0]
    identity = (first.source, first.source_id, first.project_id, first.reason)
    if any((impact.source, impact.source_id, impact.project_id, impact.reason) != identity for impact in impacts[1:]):
        raise ValueError("one logical mutation cannot combine impacts from different sources")
    usage = next(
        (impact.usage for impact in impacts if impact.usage is CredentialUsage.ENVIRONMENT_INJECTION),
        first.usage,
    )
    return CredentialImpact(
        usage=usage,
        source=first.source,
        source_id=first.source_id,
        reason=first.reason,
        project_id=first.project_id,
        affected_sandbox_ids=frozenset(sandbox_id for impact in impacts for sandbox_id in impact.affected_sandbox_ids),
        affected_session_ids=frozenset(session_id for impact in impacts for session_id in impact.affected_session_ids),
        dispositions=frozenset(disposition for impact in impacts for disposition in impact.dispositions),
    )


@dataclass(frozen=True, slots=True)
class CredentialAuditActor:
    user_id: UserId | None
    principal_type: str
    principal_id: str
    ip_address: str
    user_agent: str | None = None
    org_id: OrganizationId | None = None
    role: str | None = None

    @classmethod
    def system(cls, principal_id: str = "credential_application") -> "CredentialAuditActor":
        return cls(
            user_id=None,
            principal_type="system",
            principal_id=principal_id,
            ip_address="application",
        )


class CredentialAccessResult(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CredentialAccessContext:
    consumer_type: str
    actor: CredentialAuditActor
    consumer_id: str | None = None
    session_id: SessionId | None = None
    task_id: TaskId | None = None
    generation: int | None = None

    def __post_init__(self) -> None:
        consumer_type = self.consumer_type.strip()
        if not consumer_type:
            raise ValueError("credential access consumer type must not be blank")
        object.__setattr__(self, "consumer_type", consumer_type)


@dataclass(frozen=True, slots=True)
class CredentialAccessAuditEntry:
    id: CredentialAccessAuditId
    project_id: ProjectId
    credential_id: CredentialId
    usage: CredentialUsage
    consumer_type: str
    actor: CredentialAuditActor
    field_names: tuple[CredentialFieldName, ...]
    result: CredentialAccessResult
    credential_kind: str | None = None
    consumer_id: str | None = None
    session_id: SessionId | None = None
    task_id: TaskId | None = None
    generation: int | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.result is CredentialAccessResult.SUCCESS:
            if self.error_code is not None:
                raise ValueError("successful credential access must not have an error code")
        elif not isinstance(self.error_code, str) or not self.error_code.strip():
            raise ValueError("denied or failed credential access requires an error code")
        normalized_fields = tuple(
            sorted(
                {
                    field if isinstance(field, CredentialFieldName) else CredentialFieldName(str(field))
                    for field in self.field_names
                },
                key=str,
            )
        )
        object.__setattr__(self, "field_names", normalized_fields)
        if self.error_code is not None:
            object.__setattr__(self, "error_code", self.error_code.strip())


@dataclass(frozen=True, slots=True)
class CredentialAuditEntry:
    id: SecurityAuditId
    action: str
    project_id: ProjectId | None
    target_type: str = "credential"
    target_id: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)


class CredentialRepositoryPort(Protocol):
    async def create(self, credential_id: CredentialId, request: Any, project_id: ProjectId) -> Any: ...

    async def get(self, credential_id: CredentialId, project_id: ProjectId) -> Any | None: ...

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
        credential_ids: Sequence[CredentialId],
        *,
        project_id: ProjectId | None = None,
    ) -> Sequence[CredentialId]: ...

    async def lock_credential_scope(
        self,
        credential_id: CredentialId,
        *,
        project_id: ProjectId,
    ) -> None: ...

    def take_pending_impacts(self) -> tuple[CredentialImpact, ...]: ...

    def clear_pending_impacts(self) -> None: ...


class CredentialGroupRepositoryPort(Protocol):
    async def create_group(
        self,
        group_id: CredentialGroupId,
        request: Any,
        project_id: ProjectId,
    ) -> Any: ...

    async def get_group(
        self,
        group_id: CredentialGroupId,
        project_id: ProjectId,
    ) -> CredentialGroupResource | None: ...

    async def add_group_member(
        self,
        group_id: CredentialGroupId,
        credential_id: CredentialId,
        request: Any,
        project_id: ProjectId,
    ) -> Any: ...

    async def get_many(
        self,
        group_ids: tuple[CredentialGroupId, ...],
        project_id: ProjectId,
    ) -> tuple[CredentialGroupResource, ...]: ...

    async def list_members(
        self,
        group_ids: tuple[CredentialGroupId, ...],
        project_id: ProjectId,
    ) -> tuple[CredentialResource, ...]: ...

    async def lock_credential_groups(
        self,
        group_ids: Sequence[CredentialGroupId],
        *,
        project_id: ProjectId | None = None,
    ) -> Sequence[CredentialGroupId]: ...

    async def active_group_session_ids(
        self,
        group_id: CredentialGroupId,
        project_id: ProjectId,
    ) -> Sequence[SessionId]: ...


@dataclass(frozen=True, slots=True)
class CredentialSnapshotSource:
    agent_id: AgentId
    agent_name: str
    agent_version: int
    snapshot: Mapping[str, Any]
    source_version_id: AgentVersionId | None
    environment_id: EnvironmentId | None


@dataclass(frozen=True, slots=True)
class CredentialSnapshotSession:
    id: SessionId
    agent_id: AgentId
    project_id: ProjectId | None
    title: str
    metadata: Mapping[str, object]
    credential_group_ids: tuple[CredentialGroupId, ...]
    environment_id: EnvironmentId | None
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


class CredentialAccessAuditPort(Protocol):
    async def append(self, entry: CredentialAccessAuditEntry) -> bool: ...


class CredentialImpactPort(Protocol):
    def begin_mutation(self) -> None: ...

    async def mark_pending(self, impact: CredentialImpact) -> CredentialImpact: ...

    async def nudge_after_commit(self) -> None: ...

    def clear_pending(self) -> None: ...


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
