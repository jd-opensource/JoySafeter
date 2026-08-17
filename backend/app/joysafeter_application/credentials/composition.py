from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.ports import (
    CredentialAuditPort,
    CredentialImpactPort,
    ReferenceScanner,
)
from app.joysafeter_domain.credentials.dependencies import (
    DependencyDisposition,
    ReferenceScannerId,
    ReferenceSurfaceDescriptor,
    ReferenceSurfaceId,
    ReferenceSurfaceKind,
    ReferenceTarget,
)
from app.joysafeter_infrastructure.credentials.audit_adapter import (
    NullCredentialAuditAdapter,
    SqlAlchemyCredentialAuditAdapter,
)
from app.joysafeter_infrastructure.credentials.material_adapter import ManagedCredentialMaterialAdapter
from app.joysafeter_infrastructure.credentials.network_policy_adapter import SqlAlchemyCredentialImpactAdapter
from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import SqlAlchemyCredentialRepository
from app.joysafeter_infrastructure.repository_access.material_adapter import RepositoryAccessMaterialAdapter
from app.joysafeter_infrastructure.sensitive_material.legacy_v1 import LegacyV1MaterialProtector
from app.joysafeter_infrastructure.task_identity.material_adapter import TaskIdentityMaterialAdapter

from .binding_service import CredentialBindingService
from .group_service import CredentialGroupService
from .resource_service import CredentialResourceService
from .snapshot_service import CredentialSnapshotService, NoPersistentDependencyScanner


@dataclass(slots=True)
class SqlAlchemyCredentialUnitOfWork:
    db: AsyncSession
    credentials: SqlAlchemyCredentialRepository
    groups: SqlAlchemyCredentialRepository
    audit: CredentialAuditPort
    impacts: CredentialImpactPort

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()

    def rollback_required(self) -> bool:
        session = self.db.sync_session
        return not session.is_active or bool(session.new or session.dirty or session.deleted)


@dataclass(frozen=True, slots=True)
class CredentialApplication:
    resource_service: CredentialResourceService
    group_service: CredentialGroupService
    binding_service: CredentialBindingService
    snapshot_service: CredentialSnapshotService
    material_adapter: ManagedCredentialMaterialAdapter
    uow: SqlAlchemyCredentialUnitOfWork


def _task5_snapshot_registry() -> tuple[
    tuple[ReferenceSurfaceDescriptor, ...],
    tuple[ReferenceScanner, ...],
]:
    scanner_id = ReferenceScannerId("task5-application-material-resolution")
    return (
        (
            ReferenceSurfaceDescriptor(
                surface_id=ReferenceSurfaceId("task5-application-material-resolution"),
                kind=ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
                target=ReferenceTarget.RESOURCE,
                dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
                scanner_id=scanner_id,
                owner="joysafeter_application.credentials",
                persistent=False,
            ),
        ),
        (NoPersistentDependencyScanner(scanner_id),),
    )


def _compose_snapshot_service() -> CredentialSnapshotService:
    descriptors, scanners = _task5_snapshot_registry()
    service = CredentialSnapshotService(descriptors=descriptors, scanners=scanners)
    service.validate_scanner_registration()
    return service


def compose_credential_application(
    db: AsyncSession,
    *,
    auto_commit: bool = True,
    compatibility_mode: bool = False,
) -> CredentialApplication:
    from app.joysafeter_shared.config.settings import joysafeter_config

    snapshot_service = _compose_snapshot_service()
    protector = LegacyV1MaterialProtector(joysafeter_config.vault_encryption_key)
    impacts = SqlAlchemyCredentialImpactAdapter(db)
    material = ManagedCredentialMaterialAdapter(None, protector)
    repository = SqlAlchemyCredentialRepository(db, material=material)
    material.bind_repository(repository)
    uow = SqlAlchemyCredentialUnitOfWork(
        db=db,
        credentials=repository,
        groups=repository,
        audit=(NullCredentialAuditAdapter() if compatibility_mode else SqlAlchemyCredentialAuditAdapter(db)),
        impacts=impacts,
    )
    return CredentialApplication(
        resource_service=CredentialResourceService(
            uow,
            manage_transaction=auto_commit,
            unconditional_rollback=not compatibility_mode,
        ),
        group_service=CredentialGroupService(uow),
        binding_service=CredentialBindingService(repository),
        snapshot_service=snapshot_service,
        material_adapter=material,
        uow=uow,
    )


def compose_task_identity_material_adapter(key: str | None) -> TaskIdentityMaterialAdapter:
    return TaskIdentityMaterialAdapter(LegacyV1MaterialProtector(key))


def compose_repository_access_material_adapter(key: str | None) -> RepositoryAccessMaterialAdapter:
    return RepositoryAccessMaterialAdapter(LegacyV1MaterialProtector(key))
