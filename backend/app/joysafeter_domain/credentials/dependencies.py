from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

from .types import (
    CredentialGroupId,
    CredentialId,
    CredentialUsage,
    ProjectId,
    require_identifier,
    require_non_empty_text,
    require_project_id,
)

ReferenceSurfaceId = NewType("ReferenceSurfaceId", str)
ReferenceScannerId = NewType("ReferenceScannerId", str)


class ReferenceSurfaceKind(StrEnum):
    AGGREGATE_INTERNAL = "aggregate_internal"
    LIVE_BINDING = "live_binding"
    HISTORICAL_EXECUTABLE = "historical_executable"
    ACTIVE_SNAPSHOT = "active_snapshot"
    EPHEMERAL_CONSUMER = "ephemeral_consumer"
    LEGACY_COMPATIBILITY = "legacy_compatibility"


class ReferenceTarget(StrEnum):
    RESOURCE = "resource"
    GROUP = "group"


class DependencyDisposition(StrEnum):
    BLOCK_RESOURCE_ARCHIVE = "block_resource_archive"
    BLOCK_RESOURCE_DELETE = "block_resource_delete"
    BLOCK_GROUP_ARCHIVE = "block_group_archive"
    BLOCK_GROUP_DELETE = "block_group_delete"
    REFRESH_RUNTIME_POLICY = "refresh_runtime_policy"
    REVALIDATE_ON_ACTIVATION = "revalidate_on_activation"
    AUDIT_ONLY = "audit_only"


@dataclass(frozen=True, slots=True)
class ReferenceSurfaceDescriptor:
    surface_id: ReferenceSurfaceId
    kind: ReferenceSurfaceKind
    target: ReferenceTarget
    dispositions: frozenset[DependencyDisposition]
    scanner_id: ReferenceScannerId | None
    owner: str
    persistent: bool

    def __post_init__(self) -> None:
        require_identifier(self.surface_id, label="reference surface id")
        object.__setattr__(self, "owner", require_non_empty_text(self.owner, label="reference surface owner"))
        dispositions = frozenset(self.dispositions)
        if not dispositions or any(not isinstance(item, DependencyDisposition) for item in dispositions):
            raise ValueError("reference surface dispositions must contain supported values")
        if self.persistent and self.scanner_id is None:
            raise ValueError("persistent reference surfaces require scanner metadata")
        if self.scanner_id is not None:
            require_identifier(self.scanner_id, label="reference scanner id")
        object.__setattr__(self, "dispositions", dispositions)


@dataclass(frozen=True, slots=True)
class CredentialDependency:
    surface_id: ReferenceSurfaceId
    project_id: ProjectId
    source_id: str
    credential_id: CredentialId | None
    group_id: CredentialGroupId | None
    dispositions: frozenset[DependencyDisposition]

    def __post_init__(self) -> None:
        require_identifier(self.surface_id, label="reference surface id")
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        object.__setattr__(self, "source_id", require_non_empty_text(self.source_id, label="dependency source id"))
        if (self.credential_id is None) == (self.group_id is None):
            raise ValueError("credential dependency must target exactly one resource or group")
        if self.credential_id is not None:
            require_identifier(self.credential_id, label="credential id")
        if self.group_id is not None:
            require_identifier(self.group_id, label="credential group id")
        dispositions = frozenset(self.dispositions)
        if not dispositions or any(not isinstance(item, DependencyDisposition) for item in dispositions):
            raise ValueError("credential dependency dispositions must contain supported values")
        object.__setattr__(self, "dispositions", dispositions)

    def blocks(self, disposition: DependencyDisposition) -> bool:
        return disposition in self.dispositions


@dataclass(frozen=True, slots=True)
class CredentialImpact:
    usage: CredentialUsage
    source: str
    project_id: ProjectId
    affected_sandbox_ids: frozenset[str]
    affected_session_ids: frozenset[str]
    dispositions: frozenset[DependencyDisposition]
    source_id: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.usage, CredentialUsage):
            raise TypeError("credential impact usage must be a CredentialUsage")
        object.__setattr__(self, "source", require_non_empty_text(self.source, label="credential impact source"))
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        if self.source_id is not None:
            object.__setattr__(
                self,
                "source_id",
                require_identifier(self.source_id, label="credential impact source id"),
            )
        if self.reason is not None:
            object.__setattr__(
                self,
                "reason",
                require_non_empty_text(self.reason, label="credential impact reason"),
            )
        object.__setattr__(
            self,
            "affected_sandbox_ids",
            frozenset(require_identifier(value, label="sandbox id") for value in self.affected_sandbox_ids),
        )
        object.__setattr__(
            self,
            "affected_session_ids",
            frozenset(require_identifier(value, label="session id") for value in self.affected_session_ids),
        )
        dispositions = frozenset(self.dispositions)
        if not dispositions or any(not isinstance(item, DependencyDisposition) for item in dispositions):
            raise ValueError("credential impact dispositions must contain supported values")
        object.__setattr__(self, "dispositions", dispositions)


_BLOCK_RESOURCE = frozenset(
    {
        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
        DependencyDisposition.BLOCK_RESOURCE_DELETE,
    }
)


def _surface(
    surface_id: str,
    *,
    kind: ReferenceSurfaceKind,
    target: ReferenceTarget,
    dispositions: frozenset[DependencyDisposition],
    owner: str,
    persistent: bool = True,
) -> ReferenceSurfaceDescriptor:
    return ReferenceSurfaceDescriptor(
        surface_id=ReferenceSurfaceId(surface_id),
        kind=kind,
        target=target,
        dispositions=dispositions,
        scanner_id=ReferenceScannerId(f"{surface_id}_scanner"),
        owner=owner,
        persistent=persistent,
    )


CREDENTIAL_REFERENCE_SURFACES = (
    _surface(
        "live_agent_model_binding",
        kind=ReferenceSurfaceKind.LIVE_BINDING,
        target=ReferenceTarget.RESOURCE,
        dispositions=_BLOCK_RESOURCE,
        owner="agents",
    ),
    _surface(
        "agent_version_executable_snapshot",
        kind=ReferenceSurfaceKind.HISTORICAL_EXECUTABLE,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
        owner="agents",
    ),
    _surface(
        "trigger_webhook_auth_binding",
        kind=ReferenceSurfaceKind.LIVE_BINDING,
        target=ReferenceTarget.RESOURCE,
        dispositions=_BLOCK_RESOURCE,
        owner="triggers",
    ),
    _surface(
        "live_environment_direct_injection",
        kind=ReferenceSurfaceKind.LIVE_BINDING,
        target=ReferenceTarget.RESOURCE,
        dispositions=_BLOCK_RESOURCE,
        owner="environments",
    ),
    _surface(
        "live_environment_http_egress_binding",
        kind=ReferenceSurfaceKind.LIVE_BINDING,
        target=ReferenceTarget.RESOURCE,
        dispositions=_BLOCK_RESOURCE,
        owner="environments",
    ),
    _surface(
        "active_session_model_environment_snapshot",
        kind=ReferenceSurfaceKind.ACTIVE_SNAPSHOT,
        target=ReferenceTarget.RESOURCE,
        dispositions=_BLOCK_RESOURCE,
        owner="sessions",
    ),
    _surface(
        "session_credential_group_association",
        kind=ReferenceSurfaceKind.ACTIVE_SNAPSHOT,
        target=ReferenceTarget.GROUP,
        dispositions=frozenset(
            {
                DependencyDisposition.BLOCK_GROUP_ARCHIVE,
                DependencyDisposition.BLOCK_GROUP_DELETE,
                DependencyDisposition.REFRESH_RUNTIME_POLICY,
            }
        ),
        owner="sessions",
    ),
    _surface(
        "quickstart_model_inference",
        kind=ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
        owner="quickstart",
        persistent=False,
    ),
    _surface(
        "skill_ai_authoring_model_inference",
        kind=ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
        owner="skill_ai_authoring",
        persistent=False,
    ),
    _surface(
        "credential_group_member_ownership",
        kind=ReferenceSurfaceKind.AGGREGATE_INTERNAL,
        target=ReferenceTarget.GROUP,
        dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
        owner="credentials",
    ),
    _surface(
        "legacy_v0_v1_environment_snapshot",
        kind=ReferenceSurfaceKind.LEGACY_COMPATIBILITY,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset(
            {
                DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
                DependencyDisposition.BLOCK_RESOURCE_DELETE,
                DependencyDisposition.REVALIDATE_ON_ACTIVATION,
            }
        ),
        owner="credential_compatibility",
    ),
)
