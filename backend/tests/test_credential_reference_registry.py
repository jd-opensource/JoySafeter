from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.joysafeter_application.credentials.application_service import (
    CredentialGroupService,
    CredentialService,
)
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.lifecycle_coordinator import CredentialLifecycleCoordinator
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.snapshot_service import (
    CredentialSnapshotService,
    NoPersistentDependencyScanner,
)
from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    DependencyDisposition,
    ReferenceSurfaceKind,
    ReferenceTarget,
)
from app.joysafeter_domain.credentials.types import CredentialId as DomainCredentialId
from app.joysafeter_domain.credentials.types import ProjectId
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
)
from app.joysafeter_infrastructure.credentials.dependency_scanners import (
    ActiveSessionSnapshotScanner,
    AgentVersionExecutableSnapshotScanner,
    _snapshot_reference,
)
from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import (
    CredentialDependencies,
    SqlAlchemyCredentialRepository,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.config.settings import Settings, settings

BLOCK_RESOURCE = frozenset(
    {
        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
        DependencyDisposition.BLOCK_RESOURCE_DELETE,
    }
)
SHADOW_CREDENTIAL_ID = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f010"


async def _no_group_dependencies(_project_id, _group_id):
    return ()


EXPECTED_DESCRIPTOR_MATRIX = {
    "live_agent_model_binding": (
        ReferenceSurfaceKind.LIVE_BINDING,
        ReferenceTarget.RESOURCE,
        BLOCK_RESOURCE,
        True,
    ),
    "agent_version_executable_snapshot": (
        ReferenceSurfaceKind.HISTORICAL_EXECUTABLE,
        ReferenceTarget.RESOURCE,
        frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
        True,
    ),
    "trigger_webhook_auth_binding": (
        ReferenceSurfaceKind.LIVE_BINDING,
        ReferenceTarget.RESOURCE,
        BLOCK_RESOURCE,
        True,
    ),
    "live_environment_direct_injection": (
        ReferenceSurfaceKind.LIVE_BINDING,
        ReferenceTarget.RESOURCE,
        BLOCK_RESOURCE,
        True,
    ),
    "live_environment_http_egress_binding": (
        ReferenceSurfaceKind.LIVE_BINDING,
        ReferenceTarget.RESOURCE,
        BLOCK_RESOURCE,
        True,
    ),
    "active_session_model_environment_snapshot": (
        ReferenceSurfaceKind.ACTIVE_SNAPSHOT,
        ReferenceTarget.RESOURCE,
        BLOCK_RESOURCE,
        True,
    ),
    "session_credential_group_association": (
        ReferenceSurfaceKind.ACTIVE_SNAPSHOT,
        ReferenceTarget.GROUP,
        frozenset(
            {
                DependencyDisposition.BLOCK_GROUP_ARCHIVE,
                DependencyDisposition.BLOCK_GROUP_DELETE,
                DependencyDisposition.REFRESH_RUNTIME_POLICY,
            }
        ),
        True,
    ),
    "quickstart_model_inference": (
        ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        ReferenceTarget.RESOURCE,
        frozenset({DependencyDisposition.AUDIT_ONLY}),
        False,
    ),
    "skill_ai_authoring_model_inference": (
        ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        ReferenceTarget.RESOURCE,
        frozenset({DependencyDisposition.AUDIT_ONLY}),
        False,
    ),
    "credential_group_member_ownership": (
        ReferenceSurfaceKind.AGGREGATE_INTERNAL,
        ReferenceTarget.GROUP,
        frozenset({DependencyDisposition.AUDIT_ONLY}),
        True,
    ),
    "legacy_v0_v1_environment_snapshot": (
        ReferenceSurfaceKind.LEGACY_COMPATIBILITY,
        ReferenceTarget.RESOURCE,
        frozenset(
            {
                DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
                DependencyDisposition.BLOCK_RESOURCE_DELETE,
                DependencyDisposition.REVALIDATE_ON_ACTIVATION,
            }
        ),
        True,
    ),
}


@pytest.mark.no_db
def test_default_observation_session_uses_current_uow_bind() -> None:
    current_bind = object()
    application = compose_credential_application(
        SimpleNamespace(bind=current_bind),
        audit_actor=CredentialAuditActor.system("test"),
    )

    assert application.dependency_session_factory.kw["bind"] is current_bind


REFERENCE_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts" / "credential_reference_contract.json").read_text()
)
DEPENDENCY_REFERENCE_PATH_CASES = tuple(
    (entry, schema)
    for entry in REFERENCE_CONTRACT["reference_paths"]
    if entry["value_kind"] == "credential_id"
    for schema in entry["schemas"]
)


async def _make_project(db_session) -> str:
    suffix = str(uuid.uuid4())
    organization = Organization(name=f"registry-org-{suffix}", slug=f"registry-org-{suffix}")
    db_session.add(organization)
    await db_session.flush()
    project = Project(
        org_id=organization.id,
        name=f"registry-project-{suffix}",
        slug=f"registry-project-{suffix}",
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


def _descriptor_matrix(application) -> dict[str, tuple[object, ...]]:
    return {
        str(descriptor.surface_id): (
            descriptor.kind,
            descriptor.target,
            descriptor.dispositions,
            descriptor.persistent,
        )
        for descriptor in application.snapshot_service.descriptors
    }


def _document_for_reference_path(
    entry: dict[str, object],
    schema: str,
    credential_id: str,
) -> dict[str, object]:
    path = str(entry["path"])
    value = "ACCESS_TOKEN" if entry["value_kind"] == "credential_field" else credential_id

    def build(segments: list[str]) -> dict[str, object]:
        segment = segments[0]
        expand = segment.endswith("[*]")
        key = segment[:-3] if expand else segment
        child: object = value if len(segments) == 1 else build(segments[1:])
        return {key: [child] if expand else child}

    document = build(path.removeprefix("$.").split("."))
    if schema not in {"live", "legacy_v0"}:
        document["schema"] = REFERENCE_CONTRACT["snapshot_schemas"][schema]
    if "model_credential_id" in path or path == "$.secret_ref":
        document.update({"engine_kind": "claude", "model": {"id": "claude-sonnet"}})
    if "egress_services" in path:
        config = document.get("environment", document)
        if isinstance(config, dict) and "config" in config:
            config = config["config"]
        service = config["egress_services"][0]
        service.update({"name": "crm", "base_url": "https://crm.example.com/api"})
        if entry["value_kind"] == "credential_field":
            service["service_credential_id"] = credential_id
        inject = service.setdefault("inject", {})
        inject.setdefault("type", "bearer")
        if entry["value_kind"] == "credential_id":
            field_key = "credential_field" if schema == "v2" else "secret_key"
            inject[field_key] = "ACCESS_TOKEN"
    return document


async def _persist_reference_path_fixture(
    db_session,
    *,
    project_id: str,
    credential_id: str,
    entry: dict[str, object],
    schema: str,
):
    document = _document_for_reference_path(entry, schema, credential_id)
    if entry["document"] == "environment_config":
        source = JoySafeterEnvironment(
            project_id=project_id,
            name=f"reference-path-environment-{uuid.uuid4()}",
            config=document,
        )
    else:
        agent = JoySafeterAgent(name=f"reference-path-agent-{uuid.uuid4()}", project_id=project_id)
        db_session.add(agent)
        await db_session.flush()
        if entry["document"] == "agent_version_snapshot":
            source = JoySafeterAgentVersion(agent_id=agent.id, version=1, snapshot=document)
        else:
            source = JoySafeterSession(
                agent_id=agent.id,
                project_id=project_id,
                title=f"reference-path-session-{uuid.uuid4()}",
                agent_snapshot=document,
            )
    db_session.add(source)
    await db_session.commit()
    return source


def test_registry_has_complete_operation_specific_descriptor_matrix(db_session) -> None:
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )

    assert _descriptor_matrix(application) == EXPECTED_DESCRIPTOR_MATRIX


def test_composition_is_the_validated_one_to_one_assembly_point(db_session) -> None:
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    registry = application.snapshot_service

    registry.validate_scanner_registration()
    assert len(registry.descriptors) == len(registry.scanners)
    assert {descriptor.scanner_id for descriptor in registry.descriptors} == set(registry.scanners)

    for descriptor in registry.descriptors:
        scanner = registry.scanner(descriptor.scanner_id)
        if descriptor.persistent:
            assert not isinstance(scanner, NoPersistentDependencyScanner)
        else:
            assert isinstance(scanner, NoPersistentDependencyScanner)
            assert scanner.reason == "ephemeral_consumer"


def test_domain_descriptors_are_metadata_only() -> None:
    descriptor_fields = set(next(iter(EXPECTED_DESCRIPTOR_MATRIX)))
    assert descriptor_fields

    from app.joysafeter_domain.credentials.dependencies import ReferenceSurfaceDescriptor

    assert set(ReferenceSurfaceDescriptor.__dataclass_fields__) == {
        "surface_id",
        "kind",
        "target",
        "dispositions",
        "scanner_id",
        "owner",
        "persistent",
    }


@pytest.mark.no_db
def test_registry_mode_defaults_to_enforce_and_accepts_explicit_shadow() -> None:
    assert Settings(_env_file=None).credential_dependency_registry_mode == "enforce"
    assert (
        Settings(
            _env_file=None,
            CREDENTIAL_DEPENDENCY_REGISTRY_MODE="shadow",
        ).credential_dependency_registry_mode
        == "shadow"
    )
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            CREDENTIAL_DEPENDENCY_REGISTRY_MODE="disabled",
        )


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_enforce_resource_observation_never_calls_legacy_scanner(monkeypatch) -> None:
    legacy_called = False

    async def legacy_dependencies(*args, **kwargs):
        nonlocal legacy_called
        legacy_called = True
        raise AssertionError("legacy scanner must not run in enforce mode")

    async def registry_dependencies(project_id, credential_id):
        return ()

    coordinator = CredentialLifecycleCoordinator(
        SimpleNamespace(credentials=SimpleNamespace(dependencies=legacy_dependencies)),
        SimpleNamespace(),
        scan_resource_dependencies=registry_dependencies,
        scan_group_dependencies=lambda project_id, group_id: (),
    )
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "enforce")

    await coordinator._observe_resource(
        DomainCredentialId("cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f010"),
        "project-id",
        DependencyDisposition.BLOCK_RESOURCE_DELETE,
    )

    assert legacy_called is False


@pytest.mark.asyncio
async def test_enforce_resource_lifecycle_never_calls_legacy_repository_dependencies(
    db_session,
    project_id,
    monkeypatch,
) -> None:
    observation_factory = async_sessionmaker(
        db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    service = CredentialService(
        db_session, dependency_session_factory=observation_factory, audit_actor=CredentialAuditActor.system("test")
    )
    credential = await service.create(
        CreateCredentialRequest(
            kind="service",
            name=f"registry-enforce-resource-{uuid.uuid4()}",
            data={"TOKEN": "secret"},
        ),
        project_id=project_id,
    )

    async def forbidden_legacy_dependencies(*args, **kwargs):
        raise AssertionError("legacy dependency scanner must not run in enforce mode")

    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "enforce")
    monkeypatch.setattr(
        SqlAlchemyCredentialRepository,
        "dependencies",
        forbidden_legacy_dependencies,
    )

    archived = await service.archive(credential.id, project_id=project_id)

    assert archived.archived_at is not None


@pytest.mark.asyncio
async def test_enforce_group_lifecycle_never_calls_legacy_session_query(
    db_session,
    project_id,
    monkeypatch,
) -> None:
    observation_factory = async_sessionmaker(
        db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    service = CredentialGroupService(
        db_session, dependency_session_factory=observation_factory, audit_actor=CredentialAuditActor.system("test")
    )
    group = await service.create(
        CreateCredentialGroupRequest(name=f"registry-enforce-group-{uuid.uuid4()}"),
        project_id=project_id,
    )

    async def forbidden_legacy_sessions(*args, **kwargs):
        raise AssertionError("legacy group session query must not run in enforce mode")

    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "enforce")
    monkeypatch.setattr(
        SqlAlchemyCredentialRepository,
        "active_group_session_ids",
        forbidden_legacy_sessions,
    )

    archived = await service.archive(group.id, project_id=project_id)

    assert archived.archived_at is not None


@pytest.mark.parametrize(
    ("schema", "document", "expected_dispositions"),
    [
        (None, "agent_version", frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION})),
        (
            "joysafeter.agent_execution_snapshot.v1",
            "agent_version",
            frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION}),
        ),
        (
            None,
            "active_session",
            BLOCK_RESOURCE,
        ),
        ("joysafeter.agent_execution_snapshot.v1", "active_session", BLOCK_RESOURCE),
    ],
)
@pytest.mark.asyncio
async def test_real_snapshot_scanner_covers_top_level_legacy_secret_refs_by_schema(
    db_session,
    project_id,
    schema,
    document,
    expected_dispositions,
) -> None:
    credential = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="service",
            name=f"snapshot-ref-{uuid.uuid4()}",
            data={"TOKEN": "secret"},
        ),
        project_id=project_id,
    )
    agent = JoySafeterAgent(name=f"snapshot-agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.flush()
    snapshot = {"secret_refs": [str(credential.id)]}
    if schema is not None:
        snapshot["schema"] = schema
    if document == "agent_version":
        source = JoySafeterAgentVersion(agent_id=agent.id, version=1, snapshot=snapshot)
    else:
        source = JoySafeterSession(
            agent_id=agent.id,
            project_id=project_id,
            title=f"snapshot-session-{uuid.uuid4()}",
            agent_snapshot=snapshot,
        )
    db_session.add(source)
    await db_session.commit()

    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    dependencies = await application.snapshot_service.scan_resource(
        ProjectId(project_id),
        DomainCredentialId(str(credential.id)),
    )
    source_dependencies = [dependency for dependency in dependencies if dependency.source_id == str(source.id)]

    assert len(source_dependencies) == 1
    assert source_dependencies[0].dispositions == expected_dispositions


@pytest.mark.parametrize(
    ("document", "scanner_type"),
    [
        ("agent_version", AgentVersionExecutableSnapshotScanner),
        ("active_session", ActiveSessionSnapshotScanner),
    ],
)
@pytest.mark.asyncio
async def test_real_snapshot_scanner_rejects_legacy_alias_in_explicit_v2(
    db_session,
    project_id,
    document,
    scanner_type,
) -> None:
    credential = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="service",
            name=f"snapshot-v2-legacy-ref-{uuid.uuid4()}",
            data={"TOKEN": "secret"},
        ),
        project_id=project_id,
    )
    agent = JoySafeterAgent(name=f"snapshot-v2-agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.flush()
    snapshot = {
        "schema": "joysafeter.agent_execution_snapshot.v2",
        "secret_refs": [str(credential.id)],
    }
    source = (
        JoySafeterAgentVersion(agent_id=agent.id, version=1, snapshot=snapshot)
        if document == "agent_version"
        else JoySafeterSession(
            agent_id=agent.id,
            project_id=project_id,
            title=f"snapshot-v2-session-{uuid.uuid4()}",
            agent_snapshot=snapshot,
        )
    )
    db_session.add(source)
    await db_session.commit()

    scanner = scanner_type(db_session)
    with pytest.raises(ValueError, match="corrupt_record.*legacy alias"):
        await scanner.scan_resource(ProjectId(project_id), DomainCredentialId(str(credential.id)))


@pytest.mark.parametrize(
    ("entry", "schema"),
    DEPENDENCY_REFERENCE_PATH_CASES,
    ids=[f"{entry['scanner_fixture']}-{schema}" for entry, schema in DEPENDENCY_REFERENCE_PATH_CASES],
)
@pytest.mark.asyncio
async def test_every_credential_identity_path_has_a_real_dependency_scanner_fixture(
    db_session,
    project_id,
    entry,
    schema,
) -> None:
    credential = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="service",
            name=f"contract-path-ref-{uuid.uuid4()}",
            data={"TOKEN": "secret"},
        ),
        project_id=project_id,
    )
    source = await _persist_reference_path_fixture(
        db_session,
        project_id=project_id,
        credential_id=str(credential.id),
        entry=entry,
        schema=schema,
    )

    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    dependencies = await application.snapshot_service.scan_resource(
        ProjectId(project_id),
        DomainCredentialId(str(credential.id)),
    )
    matching = [
        dependency
        for dependency in dependencies
        if str(dependency.surface_id) == entry["surface"] and dependency.source_id == str(source.id)
    ]

    assert len(matching) == 1, entry["scanner_fixture"]
    expected_dispositions = (
        frozenset({DependencyDisposition.REVALIDATE_ON_ACTIVATION})
        if entry["document"] == "agent_version_snapshot"
        else BLOCK_RESOURCE
    )
    assert matching[0].dispositions == expected_dispositions


@pytest.mark.no_db
def test_credential_field_paths_are_codec_owned_not_dependency_edges() -> None:
    field_paths = [
        (entry["document"], entry["path"])
        for entry in REFERENCE_CONTRACT["reference_paths"]
        if entry["value_kind"] == "credential_field"
    ]

    assert field_paths
    assert all(entry["value_kind"] == "credential_id" for entry, _schema in DEPENDENCY_REFERENCE_PATH_CASES)


@pytest.mark.no_db
def test_unknown_explicit_snapshot_schema_fails_closed() -> None:
    snapshot = {
        "schema": "joysafeter.agent_execution_snapshot.v3",
        "secret_refs": ["credential-public-id"],
    }

    with pytest.raises(ValueError, match="corrupt_record.*unknown explicit Snapshot schema") as exc_info:
        _snapshot_reference(snapshot, DomainCredentialId("credential-public-id"))
    assert "joysafeter.agent_execution_snapshot.v3" not in str(exc_info.value)


@pytest.mark.parametrize(
    "scanner_type",
    [AgentVersionExecutableSnapshotScanner, ActiveSessionSnapshotScanner],
)
@pytest.mark.asyncio
@pytest.mark.no_db
async def test_unknown_explicit_snapshot_schema_fails_closed_in_real_scanners(scanner_type) -> None:
    class Rows:
        def all(self):
            return [
                (
                    "snapshot-source-id",
                    {
                        "schema": "joysafeter.agent_execution_snapshot.v3",
                        "secret_refs": ["credential-public-id"],
                    },
                )
            ]

    class FakeSession:
        async def execute(self, statement):
            return Rows()

    scanner = scanner_type(FakeSession())

    with pytest.raises(ValueError, match="corrupt_record.*unknown explicit Snapshot schema") as exc_info:
        await scanner.scan_resource(
            ProjectId("project-id"),
            DomainCredentialId("credential-public-id"),
        )
    assert "joysafeter.agent_execution_snapshot.v3" not in str(exc_info.value)


def _assert_shadow_payload_is_safe(payload: Mapping[str, object]) -> None:
    assert set(payload) == {
        "credential_id",
        "project_id",
        "old",
        "new",
        "added_ids",
        "removed_ids",
        "disposition_diff",
    }
    serialized = repr(payload).lower()
    assert "agent_snapshot" not in serialized
    assert "environment.config" not in serialized
    assert "snapshot_payload" not in serialized
    assert "environment_payload" not in serialized
    assert "api_key" not in serialized
    for side in (payload["old"], payload["new"]):
        assert isinstance(side, Mapping)
        assert set(side) == {"ids", "count", "dispositions"}


@pytest.mark.asyncio
async def test_shadow_runs_old_and_new_enforces_old_and_logs_only_safe_diff(
    db_session,
    project_id,
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "shadow")
    service = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await service.create(
        CreateCredentialRequest(
            kind="model",
            name=f"registry-model-{uuid.uuid4()}",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "must-never-appear-in-shadow-output"},
        ),
        project_id=project_id,
    )
    agent = JoySafeterAgent(
        name=f"registry-agent-{uuid.uuid4()}",
        project_id=project_id,
        model_credential_id=credential.id,
    )
    db_session.add(agent)
    await db_session.commit()

    new_scan_called = False

    async def deliberately_different_new_scan(self, scan_project_id, scan_credential_id):
        nonlocal new_scan_called
        new_scan_called = True
        return (
            CredentialDependency(
                surface_id="active_session_model_environment_snapshot",
                project_id=ProjectId(scan_project_id),
                source_id="session-public-id-only",
                credential_id=DomainCredentialId(str(scan_credential_id)),
                group_id=None,
                dispositions=BLOCK_RESOURCE,
            ),
        )

    monkeypatch.setattr(
        CredentialSnapshotService,
        "scan_resource",
        deliberately_different_new_scan,
        raising=False,
    )
    caplog.set_level(logging.INFO)

    with pytest.raises(AppError) as exc_info:
        await service.archive(credential.id, project_id=project_id)

    assert exc_info.value.code == "CREDENTIAL_IN_USE"
    assert new_scan_called is True
    records = [
        record for record in caplog.records if record.getMessage() == "credential_dependency_registry_shadow_diff"
    ]
    assert len(records) == 1
    payload = records[0].credential_dependency_diff
    _assert_shadow_payload_is_safe(payload)
    assert payload["old"]["ids"] == [str(agent.id)]
    assert payload["new"]["ids"] == ["session-public-id-only"]


@pytest.mark.asyncio
async def test_shadow_overlap_uses_independent_postgres_sessions(
    db_session,
    project_id,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "shadow")
    observation_factory = async_sessionmaker(
        db_session.bind,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )
    service = CredentialService(
        db_session,
        dependency_session_factory=observation_factory,
        audit_actor=CredentialAuditActor.system("test"),
    )
    old_started = asyncio.Event()
    new_started = asyncio.Event()
    observation_sessions = []

    async def overlapping_old_scan(credential_id, project_id):
        old_started.set()
        await asyncio.wait_for(new_started.wait(), timeout=2)
        return CredentialDependencies()

    async def overlapping_new_scan(self, scan_project_id, scan_credential_id):
        scanner_sessions = {scanner._db for scanner in self.scanners.values() if hasattr(scanner, "_db")}
        assert len(scanner_sessions) == 1
        observation_session = scanner_sessions.pop()
        observation_sessions.append(observation_session)
        assert observation_session is not db_session
        new_started.set()
        await asyncio.wait_for(old_started.wait(), timeout=2)
        return ()

    monkeypatch.setattr(service._application.uow.credentials, "dependencies", overlapping_old_scan)
    monkeypatch.setattr(CredentialSnapshotService, "scan_resource", overlapping_new_scan)

    await service._application.lifecycle._observe_resource(
        SHADOW_CREDENTIAL_ID,
        project_id,
        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
    )

    assert len(observation_sessions) == 1


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_shadow_observation_session_is_read_only_and_closed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "shadow")

    class TransactionContext:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class ObservationSession:
        def __init__(self):
            self.closed = False
            self.statements = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            self.closed = True
            return False

        def begin(self):
            return TransactionContext()

        async def execute(self, statement):
            self.statements.append(str(statement))

    observation_session = ObservationSession()

    class ObservationFactory:
        def __call__(self):
            return observation_session

    service = CredentialService(
        db=SimpleNamespace(),
        dependency_session_factory=ObservationFactory(),
        audit_actor=CredentialAuditActor.system("test"),
    )

    async def old_scan(credential_id, project_id):
        return CredentialDependencies()

    async def new_scan(self, scan_project_id, scan_credential_id):
        return ()

    monkeypatch.setattr(service._application.uow.credentials, "dependencies", old_scan)
    monkeypatch.setattr(CredentialSnapshotService, "scan_resource", new_scan)

    await service._application.lifecycle._observe_resource(
        SHADOW_CREDENTIAL_ID,
        "project-id",
        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
    )

    assert observation_session.closed is True
    assert observation_session.statements == ["SET TRANSACTION READ ONLY"]


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_shadow_new_scanner_failure_cannot_change_old_result_or_leak_payload(
    caplog,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "shadow")

    class OldDependencies:
        def as_data(self):
            return {"agents": [], "triggers": [], "environments": [], "sessions": []}

    class LegacyRepository:
        async def dependencies(self, credential_id, project_id):
            return OldDependencies()

    class FailingRegistry:
        async def scan_resource(self, scan_project_id, scan_credential_id):
            raise RuntimeError(
                "snapshot_payload={'TOKEN':'must-never-appear-in-shadow-output'} "
                "environment_payload={'secret_refs': ['credential']}"
            )

    class LegacyResourceService:
        async def archive(self, credential_id, project_id):
            return SimpleNamespace(archived_at="legacy-result")

    lifecycle = CredentialLifecycleCoordinator(
        SimpleNamespace(credentials=LegacyRepository()),
        SimpleNamespace(),
        scan_resource_dependencies=FailingRegistry().scan_resource,
        scan_group_dependencies=_no_group_dependencies,
    )

    caplog.set_level(logging.INFO)

    await lifecycle._observe_resource(
        SHADOW_CREDENTIAL_ID,
        "project-id",
        DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
    )
    archived = await LegacyResourceService().archive(SHADOW_CREDENTIAL_ID, project_id="project-id")

    assert archived.archived_at is not None
    logs = "\n".join(record.getMessage() for record in caplog.records).lower()
    assert "snapshot_payload" not in logs
    assert "environment_payload" not in logs
    assert "must-never-appear-in-shadow-output" not in logs


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_shadow_old_scanner_failure_remains_authoritative(monkeypatch) -> None:
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "shadow")
    old_error = RuntimeError("legacy-authoritative-failure")

    class LegacyRepository:
        async def dependencies(self, credential_id, project_id):
            raise old_error

    class ObservationRegistry:
        async def scan_resource(self, scan_project_id, scan_credential_id):
            return ()

    lifecycle = CredentialLifecycleCoordinator(
        SimpleNamespace(credentials=LegacyRepository()),
        SimpleNamespace(),
        scan_resource_dependencies=ObservationRegistry().scan_resource,
        scan_group_dependencies=_no_group_dependencies,
    )

    with pytest.raises(RuntimeError) as exc_info:
        await lifecycle._observe_resource(
            SHADOW_CREDENTIAL_ID,
            "project-id",
            DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
        )

    assert exc_info.value is old_error


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_shadow_child_cancelled_error_propagates(monkeypatch) -> None:
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "shadow")

    class LegacyRepository:
        async def dependencies(self, credential_id, project_id):
            return CredentialDependencies()

    class CancelledRegistry:
        async def scan_resource(self, scan_project_id, scan_credential_id):
            raise asyncio.CancelledError

    lifecycle = CredentialLifecycleCoordinator(
        SimpleNamespace(credentials=LegacyRepository()),
        SimpleNamespace(),
        scan_resource_dependencies=CancelledRegistry().scan_resource,
        scan_group_dependencies=_no_group_dependencies,
    )

    with pytest.raises(asyncio.CancelledError):
        await lifecycle._observe_resource(
            SHADOW_CREDENTIAL_ID,
            "project-id",
            DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
        )


@pytest.mark.asyncio
@pytest.mark.no_db
async def test_shadow_parent_task_cancellation_propagates(monkeypatch) -> None:
    monkeypatch.setattr(settings, "credential_dependency_registry_mode", "shadow")
    started = asyncio.Event()
    wait_forever = asyncio.Event()

    class LegacyRepository:
        async def dependencies(self, credential_id, project_id):
            started.set()
            await wait_forever.wait()

    class ObservationRegistry:
        async def scan_resource(self, scan_project_id, scan_credential_id):
            await wait_forever.wait()

    lifecycle = CredentialLifecycleCoordinator(
        SimpleNamespace(credentials=LegacyRepository()),
        SimpleNamespace(),
        scan_resource_dependencies=ObservationRegistry().scan_resource,
        scan_group_dependencies=_no_group_dependencies,
    )
    observation = asyncio.create_task(
        lifecycle._observe_resource(
            SHADOW_CREDENTIAL_ID,
            "project-id",
            DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    observation.cancel()

    with pytest.raises(asyncio.CancelledError):
        await observation
