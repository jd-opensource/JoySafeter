from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.credentials.dependencies import (
    CREDENTIAL_REFERENCE_SURFACES,
    CredentialDependency,
    DependencyDisposition,
    ReferenceScannerId,
    ReferenceSurfaceId,
)
from app.joysafeter_domain.credentials.references import (
    CredentialReferenceCodec,
    registered_reference_paths,
)
from app.joysafeter_domain.credentials.types import (
    CredentialGroupId,
    CredentialId,
    ProjectId,
    make_credential_group_id,
    make_credential_id,
    make_project_id,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterSessionCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_shared.ids import CredentialGroupId as SqlCredentialGroupId
from app.joysafeter_shared.ids import CredentialId as SqlCredentialId

BLOCK_RESOURCE = frozenset(
    {
        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
        DependencyDisposition.BLOCK_RESOURCE_DELETE,
    }
)
_REFERENCE_CODEC = CredentialReferenceCodec()
_SNAPSHOT_DOCUMENTS = frozenset({"agent_version_snapshot", "active_session_snapshot"})
_SNAPSHOT_PRIMARY_PATHS = registered_reference_paths(
    documents=_SNAPSHOT_DOCUMENTS,
    surfaces=frozenset({"agent_version_executable_snapshot", "active_session_model_environment_snapshot"}),
)
_SNAPSHOT_LEGACY_PATHS = registered_reference_paths(
    documents=_SNAPSHOT_DOCUMENTS,
    surfaces=frozenset({"legacy_v0_v1_environment_snapshot"}),
)
_ENVIRONMENT_PRIMARY_PATHS = registered_reference_paths(
    documents=frozenset({"environment_config"}),
    surfaces=frozenset({"live_environment_direct_injection", "live_environment_http_egress_binding"}),
)
_ENVIRONMENT_LEGACY_PATHS = registered_reference_paths(
    documents=frozenset({"environment_config"}),
    surfaces=frozenset({"legacy_v0_v1_environment_snapshot"}),
)


def _scanner_id(surface_id: str) -> ReferenceScannerId:
    descriptor = next(
        descriptor for descriptor in CREDENTIAL_REFERENCE_SURFACES if str(descriptor.surface_id) == surface_id
    )
    if descriptor.scanner_id is None:
        raise ValueError(f"reference surface {surface_id} has no scanner id")
    return descriptor.scanner_id


def _resource_dependency(
    surface_id: str,
    project_id: ProjectId,
    source_id: object,
    credential_id: CredentialId,
    dispositions: frozenset[DependencyDisposition],
) -> CredentialDependency:
    return CredentialDependency(
        surface_id=ReferenceSurfaceId(surface_id),
        project_id=make_project_id(str(project_id)),
        source_id=str(source_id),
        credential_id=make_credential_id(str(credential_id)),
        group_id=None,
        dispositions=dispositions,
    )


def _group_dependency(
    surface_id: str,
    project_id: ProjectId,
    source_id: object,
    group_id: CredentialGroupId,
    dispositions: frozenset[DependencyDisposition],
) -> CredentialDependency:
    return CredentialDependency(
        surface_id=ReferenceSurfaceId(surface_id),
        project_id=make_project_id(str(project_id)),
        source_id=str(source_id),
        credential_id=None,
        group_id=make_credential_group_id(str(group_id)),
        dispositions=dispositions,
    )


def _path_matches(
    credential_id: CredentialId,
    candidate_id: CredentialId,
    source_paths: tuple[str, ...],
    allowed_paths: frozenset[str],
) -> bool:
    return str(candidate_id) == str(credential_id) and bool(set(source_paths) & allowed_paths)


def _sql_credential_id(credential_id: CredentialId) -> SqlCredentialId:
    return SqlCredentialId.from_public(str(credential_id))


def _sql_group_id(group_id: CredentialGroupId) -> SqlCredentialGroupId:
    return SqlCredentialGroupId.from_public(str(group_id))


def _direct_environment_reference(config: object, credential_id: CredentialId) -> bool:
    decoded = _REFERENCE_CODEC.decode_environment(config)
    return any(
        str(reference.credential_id) == str(credential_id) and reference.source_path in _ENVIRONMENT_PRIMARY_PATHS
        for reference in decoded.direct_references
    )


def _http_egress_reference(config: object, credential_id: CredentialId) -> bool:
    decoded = _REFERENCE_CODEC.decode_environment(config)
    return any(
        _path_matches(
            credential_id,
            reference.credential_id,
            reference.source_paths,
            _ENVIRONMENT_PRIMARY_PATHS,
        )
        for reference in decoded.http_egress
    )


def _snapshot_reference(
    snapshot: object,
    credential_id: CredentialId,
) -> bool:
    decoded = _REFERENCE_CODEC.decode_snapshot(snapshot)
    if decoded.model is not None and _path_matches(
        credential_id,
        decoded.model.credential_id,
        decoded.model.source_paths,
        _SNAPSHOT_PRIMARY_PATHS,
    ):
        return True
    if any(
        str(reference.credential_id) == str(credential_id) and reference.source_path in _SNAPSHOT_PRIMARY_PATHS
        for reference in decoded.environment_references
    ):
        return True
    return any(
        _path_matches(
            credential_id,
            reference.credential_id,
            reference.source_paths,
            _SNAPSHOT_PRIMARY_PATHS,
        )
        for reference in decoded.http_egress
    )


def _legacy_environment_reference(config: object, credential_id: CredentialId) -> bool:
    decoded = _REFERENCE_CODEC.decode_environment(config)
    if any(
        str(reference.credential_id) == str(credential_id) and reference.source_path in _ENVIRONMENT_LEGACY_PATHS
        for reference in decoded.direct_references
    ):
        return True
    return any(
        _path_matches(
            credential_id,
            reference.credential_id,
            reference.source_paths,
            _ENVIRONMENT_LEGACY_PATHS,
        )
        for reference in decoded.http_egress
    )


def _legacy_snapshot_reference(
    snapshot: object,
    credential_id: CredentialId,
) -> bool:
    decoded = _REFERENCE_CODEC.decode_snapshot(snapshot)
    if decoded.model is not None and _path_matches(
        credential_id,
        decoded.model.credential_id,
        decoded.model.source_paths,
        _SNAPSHOT_LEGACY_PATHS,
    ):
        return True
    if any(
        str(reference.credential_id) == str(credential_id) and reference.source_path in _SNAPSHOT_LEGACY_PATHS
        for reference in decoded.environment_references
    ):
        return True
    return any(
        _path_matches(
            credential_id,
            reference.credential_id,
            reference.source_paths,
            _SNAPSHOT_LEGACY_PATHS,
        )
        for reference in decoded.http_egress
    )


class _ResourceScanner:
    scanner_id: ReferenceScannerId

    async def scan_group(
        self,
        project_id: ProjectId,
        group_id: CredentialGroupId,
    ) -> tuple[CredentialDependency, ...]:
        return ()


class LiveAgentModelBindingScanner(_ResourceScanner):
    scanner_id = _scanner_id("live_agent_model_binding")

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        rows = await self._db.execute(
            select(JoySafeterAgent.id).where(
                JoySafeterAgent.model_credential_id == _sql_credential_id(credential_id),
                JoySafeterAgent.project_id == str(project_id),
                JoySafeterAgent.deleted_at.is_(None),
            )
        )
        return tuple(
            _resource_dependency(
                "live_agent_model_binding",
                project_id,
                source_id,
                credential_id,
                BLOCK_RESOURCE,
            )
            for source_id in rows.scalars().all()
        )


class AgentVersionExecutableSnapshotScanner(_ResourceScanner):
    scanner_id = _scanner_id("agent_version_executable_snapshot")

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        rows = await self._db.execute(
            select(JoySafeterAgentVersion.id, JoySafeterAgentVersion.snapshot)
            .join(JoySafeterAgent, JoySafeterAgent.id == JoySafeterAgentVersion.agent_id)
            .where(JoySafeterAgent.project_id == str(project_id))
        )
        return tuple(
            _resource_dependency(
                "agent_version_executable_snapshot",
                project_id,
                version_id,
                credential_id,
                frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
            )
            for version_id, snapshot in rows.all()
            if _snapshot_reference(snapshot, credential_id)
        )


class TriggerWebhookAuthBindingScanner(_ResourceScanner):
    scanner_id = _scanner_id("trigger_webhook_auth_binding")

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        rows = await self._db.execute(
            select(JoySafeterTrigger.id).where(
                JoySafeterTrigger.webhook_auth_credential_id == _sql_credential_id(credential_id),
                JoySafeterTrigger.project_id == str(project_id),
                JoySafeterTrigger.deleted_at.is_(None),
            )
        )
        return tuple(
            _resource_dependency(
                "trigger_webhook_auth_binding",
                project_id,
                source_id,
                credential_id,
                BLOCK_RESOURCE,
            )
            for source_id in rows.scalars().all()
        )


class _EnvironmentScanner(_ResourceScanner):
    surface_id: str

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def references(self, config: object, credential_id: CredentialId) -> bool:
        raise NotImplementedError

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        rows = await self._db.execute(
            select(JoySafeterEnvironment.id, JoySafeterEnvironment.config).where(
                JoySafeterEnvironment.project_id == str(project_id),
                JoySafeterEnvironment.deleted_at.is_(None),
            )
        )
        return tuple(
            _resource_dependency(
                self.surface_id,
                project_id,
                environment_id,
                credential_id,
                BLOCK_RESOURCE,
            )
            for environment_id, config in rows.all()
            if self.references(config, credential_id)
        )


class EnvironmentDirectInjectionScanner(_EnvironmentScanner):
    surface_id = "live_environment_direct_injection"
    scanner_id = _scanner_id(surface_id)
    references = staticmethod(_direct_environment_reference)


class EnvironmentHttpEgressBindingScanner(_EnvironmentScanner):
    surface_id = "live_environment_http_egress_binding"
    scanner_id = _scanner_id(surface_id)
    references = staticmethod(_http_egress_reference)


class ActiveSessionSnapshotScanner(_ResourceScanner):
    scanner_id = _scanner_id("active_session_model_environment_snapshot")

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        rows = await self._db.execute(
            select(JoySafeterSession.id, JoySafeterSession.agent_snapshot).where(
                JoySafeterSession.project_id == str(project_id),
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.status != "terminated",
                JoySafeterSession.agent_snapshot.is_not(None),
            )
        )
        return tuple(
            _resource_dependency(
                "active_session_model_environment_snapshot",
                project_id,
                session_id,
                credential_id,
                BLOCK_RESOURCE,
            )
            for session_id, snapshot in rows.all()
            if _snapshot_reference(snapshot, credential_id)
        )


class SessionCredentialGroupAssociationScanner:
    scanner_id = _scanner_id("session_credential_group_association")

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        return ()

    async def scan_group(
        self,
        project_id: ProjectId,
        group_id: CredentialGroupId,
    ) -> tuple[CredentialDependency, ...]:
        rows = await self._db.execute(
            select(JoySafeterSessionCredentialGroup.session_id)
            .join(JoySafeterSession, JoySafeterSession.id == JoySafeterSessionCredentialGroup.session_id)
            .where(
                JoySafeterSessionCredentialGroup.credential_group_id == _sql_group_id(group_id),
                JoySafeterSession.project_id == str(project_id),
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.status != "terminated",
            )
        )
        dispositions = frozenset(
            {
                DependencyDisposition.BLOCK_GROUP_ARCHIVE,
                DependencyDisposition.BLOCK_GROUP_DELETE,
                DependencyDisposition.REFRESH_RUNTIME_POLICY,
            }
        )
        return tuple(
            _group_dependency(
                "session_credential_group_association",
                project_id,
                session_id,
                group_id,
                dispositions,
            )
            for session_id in rows.scalars().all()
        )


class CredentialGroupMemberOwnershipScanner:
    scanner_id = _scanner_id("credential_group_member_ownership")

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        return ()

    async def scan_group(
        self,
        project_id: ProjectId,
        group_id: CredentialGroupId,
    ) -> tuple[CredentialDependency, ...]:
        rows = await self._db.execute(
            select(JoySafeterCredential.id).where(
                JoySafeterCredential.group_id == _sql_group_id(group_id),
                JoySafeterCredential.project_id == str(project_id),
            )
        )
        return tuple(
            _group_dependency(
                "credential_group_member_ownership",
                project_id,
                credential_id,
                group_id,
                frozenset({DependencyDisposition.AUDIT_ONLY}),
            )
            for credential_id in rows.scalars().all()
        )


class LegacyCompatibilityDependencyScanner(_ResourceScanner):
    scanner_id = _scanner_id("legacy_v0_v1_environment_snapshot")

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> tuple[CredentialDependency, ...]:
        dependencies = []
        environment_rows = await self._db.execute(
            select(JoySafeterEnvironment.id, JoySafeterEnvironment.config).where(
                JoySafeterEnvironment.project_id == str(project_id),
                JoySafeterEnvironment.deleted_at.is_(None),
            )
        )
        dependencies.extend(
            _resource_dependency(
                "legacy_v0_v1_environment_snapshot",
                project_id,
                environment_id,
                credential_id,
                BLOCK_RESOURCE,
            )
            for environment_id, config in environment_rows.all()
            if _legacy_environment_reference(config, credential_id)
        )

        version_rows = await self._db.execute(
            select(JoySafeterAgentVersion.id, JoySafeterAgentVersion.snapshot)
            .join(JoySafeterAgent, JoySafeterAgent.id == JoySafeterAgentVersion.agent_id)
            .where(JoySafeterAgent.project_id == str(project_id))
        )
        dependencies.extend(
            _resource_dependency(
                "legacy_v0_v1_environment_snapshot",
                project_id,
                version_id,
                credential_id,
                frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
            )
            for version_id, snapshot in version_rows.all()
            if _legacy_snapshot_reference(snapshot, credential_id)
        )

        session_rows = await self._db.execute(
            select(JoySafeterSession.id, JoySafeterSession.agent_snapshot).where(
                JoySafeterSession.project_id == str(project_id),
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.status != "terminated",
                JoySafeterSession.agent_snapshot.is_not(None),
            )
        )
        dependencies.extend(
            _resource_dependency(
                "legacy_v0_v1_environment_snapshot",
                project_id,
                session_id,
                credential_id,
                BLOCK_RESOURCE,
            )
            for session_id, snapshot in session_rows.all()
            if _legacy_snapshot_reference(snapshot, credential_id)
        )
        return tuple(dependencies)


def persistent_dependency_scanners(db: AsyncSession) -> tuple[object, ...]:
    return (
        LiveAgentModelBindingScanner(db),
        AgentVersionExecutableSnapshotScanner(db),
        TriggerWebhookAuthBindingScanner(db),
        EnvironmentDirectInjectionScanner(db),
        EnvironmentHttpEgressBindingScanner(db),
        ActiveSessionSnapshotScanner(db),
        SessionCredentialGroupAssociationScanner(db),
        CredentialGroupMemberOwnershipScanner(db),
        LegacyCompatibilityDependencyScanner(db),
    )
