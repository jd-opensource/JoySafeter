from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.joysafeter_application.credentials.ports import (
    CredentialAuditActor,
    CredentialAuditPort,
    CredentialImpactPort,
    ReferenceScanner,
)
from app.joysafeter_domain.credentials.dependencies import (
    CREDENTIAL_REFERENCE_SURFACES,
    ReferenceSurfaceDescriptor,
)
from app.joysafeter_infrastructure.credentials.access_audit_adapter import (
    SqlAlchemyCredentialAccessAuditAdapter,
)
from app.joysafeter_infrastructure.credentials.audit_adapter import SqlAlchemyCredentialAuditAdapter
from app.joysafeter_infrastructure.credentials.dependency_scanners import (
    persistent_dependency_scanners,
)
from app.joysafeter_infrastructure.credentials.material_adapter import ManagedCredentialMaterialAdapter
from app.joysafeter_infrastructure.credentials.network_policy_adapter import SqlAlchemyCredentialImpactAdapter
from app.joysafeter_infrastructure.credentials.snapshot_adapter import (
    SqlAlchemyCredentialSessionRepository,
    SqlAlchemyCredentialSnapshotSourceAdapter,
)
from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import SqlAlchemyCredentialRepository
from app.joysafeter_infrastructure.repository_access.material_adapter import RepositoryAccessMaterialAdapter
from app.joysafeter_infrastructure.sensitive_material.versioned import VersionedMaterialProtector
from app.joysafeter_infrastructure.task_identity.material_adapter import TaskIdentityMaterialAdapter

from .binding_service import BindingIssuanceAuthority, CredentialBindingService
from .group_service import CredentialGroupService
from .lifecycle_coordinator import CredentialLifecycleCoordinator
from .material_access_service import CredentialMaterialAccessService
from .resource_service import CredentialResourceService
from .snapshot_service import CredentialSnapshotService, NoPersistentDependencyScanner


@dataclass(slots=True)
class SqlAlchemyCredentialUnitOfWork:
    db: AsyncSession
    credentials: SqlAlchemyCredentialRepository
    groups: SqlAlchemyCredentialRepository
    audit: CredentialAuditPort
    impacts: CredentialImpactPort
    sources: SqlAlchemyCredentialSnapshotSourceAdapter
    sessions: SqlAlchemyCredentialSessionRepository

    async def commit(self) -> None:
        await self.db.commit()

    async def rollback(self) -> None:
        await self.db.rollback()
        self.credentials.clear_pending_impacts()
        clear_pending = getattr(self.impacts, "clear_pending", None)
        if clear_pending is not None:
            clear_pending()


@dataclass(frozen=True, slots=True)
class CredentialApplication:
    resource_service: CredentialResourceService
    group_service: CredentialGroupService
    binding_service: CredentialBindingService
    snapshot_service: CredentialSnapshotService
    material_access_service: CredentialMaterialAccessService
    uow: SqlAlchemyCredentialUnitOfWork
    dependency_session_factory: async_sessionmaker[AsyncSession]
    lifecycle: CredentialLifecycleCoordinator

    async def scan_resource_dependencies(
        self,
        project_id,
        credential_id,
    ):
        async with self.dependency_session_factory() as observation_db:
            async with observation_db.begin():
                await observation_db.execute(text("SET TRANSACTION READ ONLY"))
                registry = _compose_snapshot_service(observation_db)
                return await registry.scan_resource(project_id, credential_id)

    async def scan_group_dependencies(
        self,
        project_id,
        group_id,
    ):
        async with self.dependency_session_factory() as observation_db:
            async with observation_db.begin():
                await observation_db.execute(text("SET TRANSACTION READ ONLY"))
                registry = _compose_snapshot_service(observation_db)
                return await registry.scan_group(project_id, group_id)


def _task5_snapshot_registry() -> tuple[
    tuple[ReferenceSurfaceDescriptor, ...],
    tuple[ReferenceScanner, ...],
]:
    descriptors = tuple(descriptor for descriptor in CREDENTIAL_REFERENCE_SURFACES if not descriptor.persistent)
    scanners = tuple(
        NoPersistentDependencyScanner(
            descriptor.scanner_id,
            reason="ephemeral_consumer",
        )
        for descriptor in descriptors
    )
    return descriptors, scanners


def _compose_snapshot_service(db: AsyncSession) -> CredentialSnapshotService:
    ephemeral_descriptors, ephemeral_scanners = _task5_snapshot_registry()
    persistent_descriptors = tuple(descriptor for descriptor in CREDENTIAL_REFERENCE_SURFACES if descriptor.persistent)
    descriptors = persistent_descriptors + ephemeral_descriptors
    scanners = persistent_dependency_scanners(db) + ephemeral_scanners
    service = CredentialSnapshotService(descriptors=descriptors, scanners=scanners)
    service.validate_scanner_registration()
    return service


def compose_credential_application(
    db: AsyncSession,
    *,
    audit_actor: CredentialAuditActor,
    auto_commit: bool = True,
    dependency_session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> CredentialApplication:
    from app.joysafeter_shared.config.settings import joysafeter_config

    observation_session_factory = dependency_session_factory or async_sessionmaker(
        db.bind,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    snapshot_service = _compose_snapshot_service(db)
    protector = VersionedMaterialProtector(
        joysafeter_config.vault_encryption_key,
        keyring_json=joysafeter_config.credential_encryption_keyring,
        write_key_id=joysafeter_config.credential_encryption_write_key_id,
    )
    impacts = SqlAlchemyCredentialImpactAdapter(db)
    issuance_authority = BindingIssuanceAuthority()
    material = ManagedCredentialMaterialAdapter(None, protector, issuance_authority)
    repository = SqlAlchemyCredentialRepository(db, material=material)
    material.bind_repository(repository)
    uow = SqlAlchemyCredentialUnitOfWork(
        db=db,
        credentials=repository,
        groups=repository,
        audit=SqlAlchemyCredentialAuditAdapter(
            db,
            actor=audit_actor,
        ),
        impacts=impacts,
        sources=SqlAlchemyCredentialSnapshotSourceAdapter(db),
        sessions=SqlAlchemyCredentialSessionRepository(db),
    )
    transactions = CredentialResourceService(
        uow,
        manage_transaction=auto_commit,
    )
    application_holder: dict[str, CredentialApplication] = {}

    async def scan_resource_dependencies(project_id, credential_id):
        return await application_holder["application"].scan_resource_dependencies(project_id, credential_id)

    async def scan_group_dependencies(project_id, group_id):
        return await application_holder["application"].scan_group_dependencies(project_id, group_id)

    lifecycle = CredentialLifecycleCoordinator(
        uow,
        transactions,
        scan_resource_dependencies=scan_resource_dependencies,
        scan_group_dependencies=scan_group_dependencies,
    )
    binding_service = CredentialBindingService(repository, issuance_authority)
    application = CredentialApplication(
        resource_service=transactions,
        group_service=CredentialGroupService(uow, transactions),
        binding_service=binding_service,
        snapshot_service=snapshot_service,
        material_access_service=CredentialMaterialAccessService(
            binding_service,
            material,
            SqlAlchemyCredentialAccessAuditAdapter(observation_session_factory),
        ),
        uow=uow,
        dependency_session_factory=observation_session_factory,
        lifecycle=lifecycle,
    )
    application_holder["application"] = application
    return application


def compose_task_identity_material_adapter(
    legacy_key: str | None,
    *,
    keyring_json: str | None = None,
    write_key_id: str | None = None,
) -> TaskIdentityMaterialAdapter:
    return TaskIdentityMaterialAdapter(
        VersionedMaterialProtector(
            legacy_key,
            keyring_json=keyring_json,
            write_key_id=write_key_id,
        )
    )


def compose_repository_access_material_adapter(
    legacy_key: str | None,
    *,
    keyring_json: str | None = None,
    write_key_id: str | None = None,
) -> RepositoryAccessMaterialAdapter:
    return RepositoryAccessMaterialAdapter(
        VersionedMaterialProtector(
            legacy_key,
            keyring_json=keyring_json,
            write_key_id=write_key_id,
        )
    )
