from __future__ import annotations

import ast
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select

from app.joysafeter_api.api.v1.agent_identity_capture import _encrypt
from app.joysafeter_application.credentials import composition as credential_composition
from app.joysafeter_application.credentials.binding_service import ValidatedCredentialBinding
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import (
    CredentialAuditEntry,
    CredentialUnitOfWork,
)
from app.joysafeter_application.credentials.resource_service import CredentialResourceService
from app.joysafeter_application.credentials.snapshot_service import (
    CredentialSnapshotService,
    NoPersistentDependencyScanner,
)
from app.joysafeter_domain.credentials import (
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    CredentialImpact,
    CredentialMaterial,
    CredentialUsage,
    DependencyDisposition,
    EngineKind,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpGroupBinding,
    ModelCatalogContext,
    ModelInferenceBinding,
    ProjectId,
    ReferenceSurfaceDescriptor,
    ReferenceSurfaceKind,
    ReferenceTarget,
    SensitiveValue,
)
from app.joysafeter_domain.credentials.bindings import EgressInjectKind, EgressInjectPolicy
from app.joysafeter_domain.credentials.dependencies import ReferenceScannerId, ReferenceSurfaceId
from app.joysafeter_domain.credentials.types import NormalizedEndpoint
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_infrastructure.credentials.material_adapter import (
    ManagedCredentialMaterialAdapter,
)
from app.joysafeter_infrastructure.repository_access.material_adapter import (
    RepositoryAccessMaterialAdapter,
)
from app.joysafeter_infrastructure.sensitive_material.legacy_v1 import LegacyV1MaterialProtector
from app.joysafeter_infrastructure.task_identity.material_adapter import TaskIdentityMaterialAdapter

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
TEST_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    return called


def test_legacy_credential_service_is_an_application_facade() -> None:
    path = APP_ROOT / "joysafeter_domain/services/joysafeter_credential_service.py"
    imports = _imports(path)

    assert not any(name.startswith("app.joysafeter_api") for name in imports)
    assert "app.joysafeter_domain.schemas.joysafeter_credential" not in imports
    assert "sqlalchemy" not in imports
    assert not any(name.startswith("sqlalchemy.") for name in imports)
    assert "app.joysafeter_application.credentials.composition" in imports


def test_repository_access_does_not_call_credential_service_encryption_helpers() -> None:
    path = APP_ROOT / "joysafeter_domain/services/joysafeter_session_resource_service.py"
    imports = _imports(path)
    calls = _calls(path)

    assert "app.joysafeter_domain.services.joysafeter_credential_service" not in imports
    assert "encrypt_data_for_storage" not in calls
    assert "app.joysafeter_application.credentials.composition" in imports


def test_task_identity_uses_its_purpose_specific_material_adapter() -> None:
    path = APP_ROOT / "joysafeter_api/api/v1/agent_identity_capture.py"
    imports = _imports(path)
    calls = _calls(path)

    assert "app.joysafeter_shared.security.credential_cipher" not in imports
    assert "CredentialCipher" not in calls
    assert "app.joysafeter_application.credentials.composition" in imports


def test_new_infrastructure_does_not_import_api_layer() -> None:
    for path in (APP_ROOT / "joysafeter_infrastructure").rglob("*.py"):
        assert not any(name.startswith("app.joysafeter_api") for name in _imports(path)), path


def test_purpose_material_adapters_import_only_neutral_legacy_protector() -> None:
    expected = "app.joysafeter_infrastructure.sensitive_material.legacy_v1"
    for relative_path in (
        "joysafeter_infrastructure/credentials/material_adapter.py",
        "joysafeter_infrastructure/task_identity/material_adapter.py",
        "joysafeter_infrastructure/repository_access/material_adapter.py",
    ):
        imports = _imports(APP_ROOT / relative_path)
        assert expected in imports
    assert "app.joysafeter_infrastructure.credentials.material_adapter" not in _imports(
        APP_ROOT / "joysafeter_infrastructure/task_identity/material_adapter.py"
    )
    assert "app.joysafeter_infrastructure.credentials.material_adapter" not in _imports(
        APP_ROOT / "joysafeter_infrastructure/repository_access/material_adapter.py"
    )


@dataclass
class _EncryptedMaterialRepository:
    fields: dict[str, str]

    async def load_encrypted_material(self, credential_id: CredentialId, project_id: ProjectId) -> dict[str, str]:
        return dict(self.fields)


@pytest.mark.asyncio
async def test_managed_material_adapter_returns_only_binding_authorized_fields() -> None:
    protector = LegacyV1MaterialProtector(TEST_KEY)
    repository = _EncryptedMaterialRepository(
        {
            "TOKEN": protector.protect("allowed"),
            "OTHER": protector.protect("must-not-leak"),
        }
    )
    adapter = ManagedCredentialMaterialAdapter(repository, protector)
    binding = HttpEgressBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("credential-1"),
        endpoint=NormalizedEndpoint("https://example.com/api"),
        inject=EgressInjectPolicy(
            kind=EgressInjectKind.BEARER,
            credential_field=CredentialFieldName("TOKEN"),
        ),
    )

    resolved = await adapter.load(
        ValidatedCredentialBinding(
            binding=binding,
            authorized_fields=frozenset({CredentialFieldName("TOKEN")}),
        )
    )

    assert dict(resolved.fields) == {CredentialFieldName("TOKEN"): "allowed"}
    assert "must-not-leak" not in repr(resolved)


@pytest.mark.asyncio
async def test_environment_injection_is_the_only_binding_that_can_load_all_fields() -> None:
    protector = LegacyV1MaterialProtector(TEST_KEY)
    repository = _EncryptedMaterialRepository(
        {
            "TOKEN": protector.protect("one"),
            "SECOND": protector.protect("two"),
        }
    )
    adapter = ManagedCredentialMaterialAdapter(repository, protector)
    binding = EnvironmentInjectionBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("credential-1"),
    )

    resolved = await adapter.load(ValidatedCredentialBinding.all_fields(binding))

    assert dict(resolved.fields) == {
        CredentialFieldName("TOKEN"): "one",
        CredentialFieldName("SECOND"): "two",
    }


def test_non_environment_binding_cannot_request_all_fields() -> None:
    binding = HttpEgressBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("credential-1"),
        endpoint=NormalizedEndpoint("https://example.com/api"),
        inject=EgressInjectPolicy(
            kind=EgressInjectKind.BEARER,
            credential_field=CredentialFieldName("TOKEN"),
        ),
    )

    with pytest.raises(ValueError, match="Environment Injection"):
        ValidatedCredentialBinding.all_fields(binding)


def test_purpose_specific_adapters_share_only_legacy_v1_protector() -> None:
    protector = LegacyV1MaterialProtector(TEST_KEY)
    identity = TaskIdentityMaterialAdapter(protector)
    repository = RepositoryAccessMaterialAdapter(protector)

    identity_ciphertext = identity.protect_identity_credential("identity-value")
    repository_ciphertext = repository.protect_repository_token("repository-value")

    assert identity_ciphertext.startswith("enc:v1:")
    assert repository_ciphertext.startswith("enc:v1:")
    assert identity.reveal_identity_credential(identity_ciphertext) == "identity-value"
    assert repository.reveal_repository_token(repository_ciphertext) == "repository-value"

    identity_imports = _imports(APP_ROOT / "joysafeter_infrastructure/task_identity/material_adapter.py")
    repository_imports = _imports(APP_ROOT / "joysafeter_infrastructure/repository_access/material_adapter.py")
    assert not any(name.startswith("app.joysafeter_application") for name in identity_imports)
    assert not any(name.startswith("app.joysafeter_application") for name in repository_imports)


@dataclass
class _FakeCredentialRepository:
    result: Any = object()
    error: Exception | None = None

    async def create(self, request: Any, project_id: str) -> Any:
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class _FakeGroupRepository:
    pass


@dataclass
class _FakeAudit:
    entries: list[CredentialAuditEntry] = field(default_factory=list)

    async def append(self, entry: CredentialAuditEntry) -> None:
        self.entries.append(entry)


@dataclass
class _FakeImpacts:
    pending: list[CredentialImpact] = field(default_factory=list)

    async def mark_pending(self, impact: CredentialImpact) -> CredentialImpact:
        self.pending.append(impact)
        return impact

    async def nudge_after_commit(self) -> None:
        return None


@dataclass
class _FakeUnitOfWork:
    credentials: _FakeCredentialRepository
    groups: _FakeGroupRepository = field(default_factory=_FakeGroupRepository)
    audit: _FakeAudit = field(default_factory=_FakeAudit)
    impacts: _FakeImpacts = field(default_factory=_FakeImpacts)
    commits: int = 0
    rollbacks: int = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def test_unit_of_work_protocol_exposes_transaction_collaborators() -> None:
    annotations = CredentialUnitOfWork.__annotations__
    assert set(("credentials", "groups", "audit", "impacts")) <= set(annotations)
    assert callable(getattr(CredentialUnitOfWork, "commit"))
    assert callable(getattr(CredentialUnitOfWork, "rollback"))


@pytest.mark.asyncio
async def test_application_service_commits_mutation_and_audit_together() -> None:
    result = object()
    uow = _FakeUnitOfWork(credentials=_FakeCredentialRepository(result=result))
    service = CredentialResourceService(uow)

    assert await service.create(object(), project_id="project-1") is result
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert [entry.action for entry in uow.audit.entries] == ["credential.created"]


@pytest.mark.asyncio
async def test_application_service_rolls_back_repository_failure() -> None:
    uow = _FakeUnitOfWork(credentials=_FakeCredentialRepository(error=RuntimeError("write failed")))
    service = CredentialResourceService(uow)

    with pytest.raises(RuntimeError, match="write failed"):
        await service.create(object(), project_id="project-1")

    assert uow.commits == 0
    assert uow.rollbacks == 1
    assert uow.audit.entries == []


def test_managed_adapter_is_the_only_importer_of_domain_reveal_seam() -> None:
    importers: list[Path] = []
    for path in APP_ROOT.rglob("*.py"):
        if path == APP_ROOT / "joysafeter_domain/credentials/material.py":
            continue
        if "_issue_material_reveal_capability" in path.read_text():
            importers.append(path.relative_to(APP_ROOT))

    assert importers == [Path("joysafeter_infrastructure/credentials/material_adapter.py")]


def test_managed_adapter_protects_domain_material_without_exposing_reveal_capability() -> None:
    protector = LegacyV1MaterialProtector(TEST_KEY)
    adapter = ManagedCredentialMaterialAdapter(_EncryptedMaterialRepository({}), protector)
    material = CredentialMaterial({CredentialFieldName("TOKEN"): SensitiveValue("managed-value")})

    protected = adapter.protect(material)

    assert protected["TOKEN"].startswith("enc:v1:")
    assert protector.reveal(protected["TOKEN"]) == "managed-value"


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"project-{uuid.uuid4()}", slug=f"project-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.mark.asyncio
async def test_production_composition_binding_service_maps_sqlalchemy_resource(db_session) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(
            kind="model",
            name="composed-model",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "secret"},
        ),
        project_id=project_id,
    )
    binding = ModelInferenceBinding(
        project_id=ProjectId(project_id),
        credential_id=CredentialId(str(credential.id)),
        engine_kind=EngineKind.CODEX,
        model_id="gpt-test",
    )

    validated = await application.binding_service.validate(
        binding,
        requested_fields=frozenset({CredentialFieldName("API_KEY")}),
        catalog_context=ModelCatalogContext(
            provider_id="openai",
            protocol_id="openai",
            engine_kind=EngineKind.CODEX,
            model_ids=frozenset({"gpt-test"}),
        ),
    )

    assert validated.binding is binding
    assert validated.authorized_fields == frozenset({CredentialFieldName("API_KEY")})


@pytest.mark.asyncio
async def test_production_composition_group_service_maps_groups_and_members(db_session) -> None:
    project_id = await _make_project(db_session)
    protector = LegacyV1MaterialProtector(TEST_KEY)
    group = JoySafeterCredentialGroup(project_id=project_id, name="composed-group")
    db_session.add(group)
    await db_session.flush()
    member = JoySafeterCredential(
        project_id=project_id,
        kind="mcp",
        name="member",
        data={"token_value": protector.protect("token")},
        credential_type="static_bearer",
        group_id=group.id,
        mcp_server_url="https://mcp.example.com",
        normalized_mcp_server_url="https://mcp.example.com",
    )
    db_session.add(member)
    await db_session.commit()
    application = compose_credential_application(db_session)
    binding = McpGroupBinding(
        project_id=ProjectId(project_id),
        group_ids=(CredentialGroupId(str(group.id)),),
        declared_server_urls=(),
    )

    await application.group_service.validate_binding(binding)


@pytest.mark.asyncio
async def test_production_composition_orders_mutation_audit_impact_commit_nudge(
    db_session,
    monkeypatch,
) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="ordered", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    sandbox = JoySafeterSandbox(
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )
    db_session.add(sandbox)
    await db_session.commit()
    credential_id = credential.id
    sandbox_id = sandbox.id
    events: list[str] = []
    resolved_impacts: list[CredentialImpact] = []

    original_update = application.uow.credentials.update
    original_append = application.uow.audit.append
    original_mark = application.uow.impacts.mark_pending

    async def recorded_update(*args, **kwargs):
        events.append("mutation")
        return await original_update(*args, **kwargs)

    async def recorded_append(entry):
        events.append("audit")
        await original_append(entry)

    async def recorded_mark(impact):
        events.append("impact")
        resolved = await original_mark(impact)
        resolved_impacts.append(resolved)
        return resolved

    async def recorded_nudge():
        events.append("nudge")

    monkeypatch.setattr(application.uow.credentials, "update", recorded_update)
    monkeypatch.setattr(application.uow.audit, "append", recorded_append)
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)
    sqlalchemy_event.listen(db_session.sync_session, "after_commit", lambda session: events.append("commit"))

    await application.resource_service.update(
        credential_id,
        UpdateCredentialRequest(data={"TOKEN": "new"}),
        project_id=project_id,
    )

    assert events == ["mutation", "audit", "impact", "commit", "nudge"]
    assert len(resolved_impacts) == 1
    impact = resolved_impacts[0]
    assert impact.usage is CredentialUsage.HTTP_EGRESS
    assert impact.source == "credential"
    assert impact.project_id == ProjectId(project_id)
    assert impact.affected_sandbox_ids == frozenset({str(sandbox_id)})
    assert impact.affected_session_ids == frozenset()
    assert impact.dispositions == frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY})
    assert (
        await db_session.execute(select(JoySafeterSandbox.networking_status).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one() == "pending"
    audit_rows = (
        (
            await db_session.execute(
                select(SecurityAuditLog).where(
                    SecurityAuditLog.event_type == "credential.updated",
                    SecurityAuditLog.details["project_id"].astext == project_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1


@pytest.mark.asyncio
async def test_production_composition_rolls_back_unconditionally_before_commit(
    db_session,
    monkeypatch,
) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="rollback-original", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    credential_id = credential.id
    events: list[str] = []
    original_update = application.uow.credentials.update

    async def recorded_update(*args, **kwargs):
        events.append("mutation")
        return await original_update(*args, **kwargs)

    async def failing_audit(entry):
        events.append("audit")
        raise RuntimeError("audit failed")

    monkeypatch.setattr(application.uow.credentials, "update", recorded_update)
    monkeypatch.setattr(application.uow.audit, "append", failing_audit)
    sqlalchemy_event.listen(db_session.sync_session, "after_rollback", lambda session: events.append("rollback"))

    with pytest.raises(RuntimeError, match="audit failed"):
        await application.resource_service.update(
            credential_id,
            UpdateCredentialRequest(name="rollback-changed"),
            project_id=project_id,
        )

    assert events == ["mutation", "audit", "rollback"]
    persisted_name = (
        await db_session.execute(select(JoySafeterCredential.name).where(JoySafeterCredential.id == credential_id))
    ).scalar_one()
    assert persisted_name == "rollback-original"


@pytest.mark.asyncio
async def test_post_commit_nudge_failure_is_best_effort(db_session, monkeypatch) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="nudge", data={"TOKEN": "old"}),
        project_id=project_id,
    )

    async def failing_nudge():
        raise RuntimeError("relay unavailable")

    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", failing_nudge)

    updated = await application.resource_service.update(
        credential.id,
        UpdateCredentialRequest(name="nudge-updated"),
        project_id=project_id,
    )

    assert updated.name == "nudge-updated"


def test_credential_impact_is_authoritative_typed_contract() -> None:
    impact = CredentialImpact(
        usage=CredentialUsage.HTTP_EGRESS,
        source="credential",
        project_id=ProjectId("project-1"),
        affected_sandbox_ids=frozenset({"sandbox-1"}),
        affected_session_ids=frozenset({"session-1"}),
        dispositions=frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY}),
    )

    assert impact.usage is CredentialUsage.HTTP_EGRESS
    assert impact.source == "credential"
    assert impact.project_id == ProjectId("project-1")


def test_task_identity_blank_material_is_not_misclassified_as_key_error() -> None:
    with pytest.raises(ValueError, match="identity credential must be non-empty"):
        _encrypt("", TEST_KEY)


def test_credential_facade_getattr_is_safe_before_initialization() -> None:
    facade = CredentialService.__new__(CredentialService)

    with pytest.raises(AttributeError, match="missing"):
        getattr(facade, "missing")


@dataclass(frozen=True)
class _Scanner:
    scanner_id: ReferenceScannerId

    async def scan_resource(self, project_id, credential_id):
        return ()


def _persistent_descriptor(scanner_id: str) -> ReferenceSurfaceDescriptor:
    return ReferenceSurfaceDescriptor(
        surface_id=ReferenceSurfaceId(f"surface-{scanner_id}"),
        kind=ReferenceSurfaceKind.LIVE_BINDING,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.BLOCK_RESOURCE_ARCHIVE}),
        scanner_id=ReferenceScannerId(scanner_id),
        owner="test",
        persistent=True,
    )


def _ephemeral_descriptor(scanner_id: str) -> ReferenceSurfaceDescriptor:
    return ReferenceSurfaceDescriptor(
        surface_id=ReferenceSurfaceId(f"surface-{scanner_id}"),
        kind=ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
        scanner_id=ReferenceScannerId(scanner_id),
        owner="test",
        persistent=False,
    )


def test_scanner_registry_rejects_duplicate_scanners() -> None:
    scanner_id = ReferenceScannerId("scanner-1")
    service = CredentialSnapshotService(
        descriptors=(_persistent_descriptor("scanner-1"),),
        scanners=(_Scanner(scanner_id), _Scanner(scanner_id)),
    )

    with pytest.raises(ValueError, match="duplicate"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_missing_persistent_scanner() -> None:
    service = CredentialSnapshotService(descriptors=(_persistent_descriptor("scanner-1"),))

    with pytest.raises(ValueError, match="missing"):
        service.validate_scanner_registration()


def test_scanner_registry_accepts_explicit_no_persistent_scanner() -> None:
    scanner_id = ReferenceScannerId("ephemeral-scanner")
    service = CredentialSnapshotService(
        descriptors=(_ephemeral_descriptor(str(scanner_id)),),
        scanners=(NoPersistentDependencyScanner(scanner_id),),
    )

    service.validate_scanner_registration()

    assert service.scanner(scanner_id).reason == "ephemeral_consumer"


def test_scanner_registry_rejects_missing_ephemeral_scanner() -> None:
    service = CredentialSnapshotService(descriptors=(_ephemeral_descriptor("ephemeral-scanner"),))

    with pytest.raises(ValueError, match="missing"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_descriptor_without_scanner_metadata() -> None:
    descriptor = ReferenceSurfaceDescriptor(
        surface_id=ReferenceSurfaceId("ephemeral-surface"),
        kind=ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
        scanner_id=None,
        owner="test",
        persistent=False,
    )
    service = CredentialSnapshotService(descriptors=(descriptor,))

    with pytest.raises(ValueError, match="descriptors_without_scanners"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_concrete_ephemeral_scanner() -> None:
    scanner_id = ReferenceScannerId("ephemeral-scanner")
    service = CredentialSnapshotService(
        descriptors=(_ephemeral_descriptor(str(scanner_id)),),
        scanners=(_Scanner(scanner_id),),
    )

    with pytest.raises(ValueError, match="wrong_scanner_kinds"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_no_persistent_scanner_for_persistent_descriptor() -> None:
    scanner_id = ReferenceScannerId("persistent-scanner")
    service = CredentialSnapshotService(
        descriptors=(_persistent_descriptor(str(scanner_id)),),
        scanners=(NoPersistentDependencyScanner(scanner_id),),
    )

    with pytest.raises(ValueError, match="wrong_scanner_kinds"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_unknown_scanner() -> None:
    service = CredentialSnapshotService(
        descriptors=(_ephemeral_descriptor("ephemeral-scanner"),),
        scanners=(NoPersistentDependencyScanner(ReferenceScannerId("unknown-scanner")),),
    )

    with pytest.raises(ValueError, match="extra"):
        service.validate_scanner_registration()


@pytest.mark.parametrize("registration", ["missing", "duplicate", "wrong_kind"])
def test_canonical_composition_rejects_invalid_ephemeral_registration(
    db_session,
    monkeypatch,
    registration: str,
) -> None:
    scanner_id = ReferenceScannerId("ephemeral-scanner")
    descriptor = _ephemeral_descriptor(str(scanner_id))
    scanners = {
        "missing": (),
        "duplicate": (
            NoPersistentDependencyScanner(scanner_id),
            NoPersistentDependencyScanner(scanner_id),
        ),
        "wrong_kind": (_Scanner(scanner_id),),
    }[registration]
    monkeypatch.setattr(
        credential_composition,
        "_task5_snapshot_registry",
        lambda: ((descriptor,), scanners),
        raising=False,
    )

    with pytest.raises(ValueError, match="credential scanner registry mismatch"):
        compose_credential_application(db_session)


def test_canonical_composition_registers_validated_task5_scanners(db_session) -> None:
    application = compose_credential_application(db_session)

    assert application.snapshot_service.descriptors
    application.snapshot_service.validate_scanner_registration()
    assert all(
        isinstance(application.snapshot_service.scanner(descriptor.scanner_id), NoPersistentDependencyScanner)
        for descriptor in application.snapshot_service.descriptors
    )
