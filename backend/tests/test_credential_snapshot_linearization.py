from __future__ import annotations

import ast
import asyncio
import importlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_application.agents import compose_agent_application
from app.joysafeter_application.credentials.application_service import (
    CredentialGroupService,
    CredentialService,
)
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.snapshot_service import CreateCredentialAwareSession
from app.joysafeter_application.sessions.creation_service import SessionCreationService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterEngineKind,
)
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import EnvironmentId

ROOT = Path(__file__).resolve().parents[1]


def _snapshot_api():
    module = importlib.import_module("app.joysafeter_application.credentials.snapshot_service")
    command_type = getattr(module, "CreateCredentialAwareSession", None)
    create = getattr(module, "create_session_from_source", None)
    assert command_type is not None, "Task 11 command is missing"
    assert callable(create), "Task 11 application service is missing"
    return command_type, create


async def _make_project(db: AsyncSession) -> str:
    suffix = str(uuid.uuid4())
    organization = Organization(name=f"snapshot-org-{suffix}", slug=f"snapshot-org-{suffix}")
    db.add(organization)
    await db.flush()
    project = Project(
        org_id=organization.id,
        name=f"snapshot-project-{suffix}",
        slug=f"snapshot-project-{suffix}",
    )
    db.add(project)
    await db.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session: AsyncSession) -> str:
    return await _make_project(db_session)


async def _model_credential(db: AsyncSession, project_id: str):
    return await CredentialService(db, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="model",
            name=f"snapshot-model-{uuid.uuid4()}",
            provider="anthropic",
            protocol="anthropic_messages",
            data={"API_KEY": "snapshot-secret"},
        ),
        project_id=project_id,
    )


async def _agent(
    db: AsyncSession,
    project_id: str,
    *,
    model_credential_id=None,
    mcp_servers: list[dict[str, str]] | None = None,
):
    return await compose_agent_application(db).commands.create_agent(
        JoySafeterCreateAgentRequest(
            name=f"snapshot-agent-{uuid.uuid4()}",
            engine_kind=JoySafeterEngineKind.CLAUDE,
            model_credential_id=model_credential_id,
            mcp_servers=mcp_servers or [],
        ),
        project_id=project_id,
    )


async def _group(db: AsyncSession, project_id: str):
    return await CredentialGroupService(db, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialGroupRequest(name=f"snapshot-group-{uuid.uuid4()}"),
        project_id=project_id,
    )


def _command(
    command_type,
    *,
    project_id: str,
    agent,
    pinned_version=None,
    group_ids=(),
    environment_config_overlay=None,
    environment_mount_resources=(),
):
    return command_type(
        project_id=project_id,
        agent_id=agent.id,
        pinned_agent_version=pinned_version,
        environment_ref=None,
        credential_group_ids=tuple(group_ids),
        title="Credential snapshot linearization",
        metadata={"caller": "test"},
        caller="test",
        environment_config_overlay=environment_config_overlay,
        environment_mount_resources=environment_mount_resources,
    )


async def _environment(
    db: AsyncSession,
    *,
    project_id: str | None,
    archived: bool = False,
    deleted: bool = False,
) -> JoySafeterEnvironment:
    now = datetime.now(timezone.utc)
    environment = JoySafeterEnvironment(
        project_id=project_id,
        name=f"snapshot-environment-{uuid.uuid4()}",
        description="",
        config={},
        image_version=1,
        archived_at=now if archived else None,
        deleted_at=now if deleted else None,
    )
    db.add(environment)
    await db.commit()
    return environment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("missing", "SESSION_ENVIRONMENT_NOT_FOUND"),
        ("cross_project", "SESSION_ENVIRONMENT_NOT_FOUND"),
        ("archived", "ENVIRONMENT_ARCHIVED"),
        ("deleted", "SESSION_ENVIRONMENT_NOT_FOUND"),
    ],
)
async def test_session_creation_validates_canonical_environment_binding(
    db_session: AsyncSession,
    project_id: str,
    case: str,
    expected_code: str,
) -> None:
    agent = await _agent(db_session, project_id)
    if case == "missing":
        environment_id = EnvironmentId.new()
    elif case == "cross_project":
        environment_id = (await _environment(db_session, project_id=await _make_project(db_session))).id
    else:
        environment_id = (
            await _environment(
                db_session,
                project_id=project_id,
                archived=case == "archived",
                deleted=case == "deleted",
            )
        ).id

    with pytest.raises(AppError) as exc_info:
        await SessionCreationService(db_session, audit_actor=CredentialAuditActor.system("test")).create_from_source(
            CreateCredentialAwareSession(
                project_id=project_id,
                agent_id=agent.id,
                environment_ref=str(environment_id),
                caller="test",
            )
        )

    assert exc_info.value.code == expected_code
    assert await db_session.scalar(select(func.count()).select_from(JoySafeterSession)) == 0


@pytest.mark.asyncio
async def test_two_created_sessions_isolate_nested_overlay_and_typed_mounts(
    db_session: AsyncSession,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    agent = await _agent(db_session, project_id)
    overlay = {"packages": {"apt": ["git"]}, "env_vars": {"MODE": "test"}}
    mounts = ({"type": "storage", "name": "data", "volume_ref": "volume", "mount_path": "/workspace/data"},)
    first_command = _command(
        command_type,
        project_id=project_id,
        agent=agent,
        environment_config_overlay=overlay,
        environment_mount_resources=mounts,
    )
    second_command = _command(
        command_type,
        project_id=project_id,
        agent=agent,
        environment_config_overlay=overlay,
        environment_mount_resources=mounts,
    )
    first_command.environment_config_overlay["packages"]["apt"].append("curl")
    first_command.environment_mount_resources[0]["name"] = "first-only"

    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    first = await create(first_command, application.uow)
    second = await create(second_command, application.uow)

    first_config = first.agent_snapshot["environment"]["config"]
    second_config = second.agent_snapshot["environment"]["config"]
    assert first_config["packages"]["apt"] == ["git", "curl"]
    assert second_config["packages"]["apt"] == ["git"]
    assert first_config["mount_resources"][0]["name"] == "first-only"
    assert second_config["mount_resources"][0]["name"] == "data"


def _production_create_session_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text())
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "create_session"
    ]


def test_snapshot_callers_submit_source_commands_and_scheduler_uses_kernel_service() -> None:
    python_paths = (
        ROOT / "app/joysafeter_api/api/v1/sessions.py",
        ROOT / "app/joysafeter_api/api/v1/tasks.py",
        ROOT / "app/joysafeter_application/triggers/execution_service.py",
    )
    forbidden = []
    for path in python_paths:
        for call in _production_create_session_calls(path):
            if any(keyword.arg == "agent_snapshot" for keyword in call.keywords):
                forbidden.append(str(path.relative_to(ROOT)))
    assert forbidden == []

    scheduler = (ROOT / "app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs").read_text()
    production = scheduler.split("#[cfg(test)]", 1)[0]
    assert "build_agent_execution_snapshot" not in production
    assert "queries::create_session" not in production
    assert "credentials::snapshot" in production
    assert "CredentialStore" in production


def test_canonical_snapshot_decoder_collects_model_and_environment_references() -> None:
    references = importlib.import_module("app.joysafeter_domain.credentials.references")
    decode_snapshot = getattr(references, "decode_snapshot", None)
    assert callable(decode_snapshot), "canonical Snapshot decoder is missing"
    compatibility_id = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f010"
    environment_id = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f011"
    http_id = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f012"
    model_id = "cred_018f6f42-0a51-7cc4-98c8-4f6f0ca5f013"

    decoded = decode_snapshot(
        {
            "schema": "joysafeter.agent_execution_snapshot.v1",
            "engine_kind": "claude",
            "model": {"id": "claude-sonnet-4"},
            "model_credential_id": model_id,
            "environment_credential_ids": [compatibility_id],
            "environment": {
                "config": {
                    "secret_refs": [environment_id],
                    "egress_services": [
                        {
                            "base_url": "https://api.example.com",
                            "service_credential_id": http_id,
                            "inject": {"type": "bearer", "secret_key": "TOKEN"},
                        }
                    ],
                }
            },
        }
    )

    assert decoded.schema == "v1"
    assert decoded.model.credential_id == model_id
    assert decoded.model.model_id == "claude-sonnet-4"
    assert decoded.environment_credential_ids == (compatibility_id, environment_id)
    assert tuple(reference.credential_id for reference in decoded.http_egress) == (http_id,)
    assert decoded.credential_ids == (compatibility_id, environment_id, http_id, model_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lifecycle", "expected_code"),
    (("archive", "CREDENTIAL_STATE_INVALID"), ("soft_delete", "CREDENTIAL_NOT_FOUND")),
)
async def test_pinned_agent_version_revalidates_credential_and_creates_no_session(
    db_session: AsyncSession,
    project_id: str,
    lifecycle: str,
    expected_code: str,
) -> None:
    command_type, create = _snapshot_api()
    credential = await _model_credential(db_session, project_id)
    agent = await _agent(db_session, project_id, model_credential_id=credential.id)
    await db_session.execute(
        update(JoySafeterAgent)
        .where(JoySafeterAgent.id == agent.id)
        .values(model_credential_id=None, updated_at=datetime.now(timezone.utc))
    )
    await db_session.commit()
    await getattr(CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")), lifecycle)(
        credential.id, project_id=project_id
    )

    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )
    with pytest.raises(AppError) as exc:
        await create(
            _command(command_type, project_id=project_id, agent=agent, pinned_version=1),
            application.uow,
        )

    assert exc.value.code == expected_code
    count = await db_session.scalar(select(func.count()).select_from(JoySafeterSession))
    assert count == 0


@pytest.mark.asyncio
async def test_pinned_explicit_v2_agent_version_persists_new_session_as_v1(
    db_session: AsyncSession,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    agent = await _agent(db_session, project_id)
    version = await db_session.scalar(
        select(JoySafeterAgentVersion).where(
            JoySafeterAgentVersion.agent_id == agent.id,
            JoySafeterAgentVersion.version == 1,
        )
    )
    assert version is not None
    explicit_v2 = dict(version.snapshot)
    explicit_v2["schema"] = "joysafeter.agent_execution_snapshot.v2"
    explicit_v2.pop("secret_refs", None)
    explicit_v2["environment_credential_ids"] = []
    version.snapshot = explicit_v2
    await db_session.commit()

    actor = CredentialAuditActor(
        user_id="snapshot-user",
        principal_type="api_key",
        principal_id="snapshot-key",
        ip_address="203.0.113.20",
        user_agent="snapshot-test/1.0",
    )
    session = await SessionCreationService(db_session, audit_actor=actor).create_from_source(
        _command(command_type, project_id=project_id, agent=agent, pinned_version=1)
    )
    await db_session.refresh(session)

    assert session.agent_snapshot["schema"] == "joysafeter.agent_execution_snapshot.v1"
    assert session.agent_snapshot["secret_refs"] == []
    assert "environment_credential_ids" not in session.agent_snapshot
    audit = await db_session.scalar(
        select(SecurityAuditLog).where(
            SecurityAuditLog.event_type == "session.snapshot.created",
            SecurityAuditLog.details["target_id"].astext == str(session.id),
        )
    )
    assert audit is not None
    assert audit.user_id == "snapshot-user"
    assert audit.ip_address == "203.0.113.20"
    assert audit.user_agent == "snapshot-test/1.0"
    assert audit.details["principal_type"] == "api_key"
    assert audit.details["principal_id"] == "snapshot-key"


async def _pause_after_locked_source(application, locked: asyncio.Event, release: asyncio.Event) -> None:
    original = application.uow.sources.load

    async def paused(command, *, for_update=False):
        source = await original(command, for_update=for_update)
        if for_update:
            locked.set()
            await release.wait()
        return source

    application.uow.sources.load = paused


async def _pause_after_locked_credentials(application, locked: asyncio.Event, release: asyncio.Event) -> None:
    original = application.uow.credentials.lock_credentials

    async def paused(credential_ids, *, project_id=None):
        result = await original(credential_ids, project_id=project_id)
        locked.set()
        await release.wait()
        return result

    application.uow.credentials.lock_credentials = paused


@pytest.mark.asyncio
async def test_snapshot_create_serializes_against_credential_archive(
    db_session: AsyncSession,
    postgres_url: str,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    credential = await _model_credential(db_session, project_id)
    agent = await _agent(db_session, project_id, model_credential_id=credential.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    locked, release = asyncio.Event(), asyncio.Event()
    try:
        async with factory() as create_db, factory() as archive_db:
            application = compose_credential_application(
                create_db,
                audit_actor=CredentialAuditActor.system("test"),
                auto_commit=False,
            )
            await _pause_after_locked_credentials(application, locked, release)
            create_task = asyncio.create_task(
                create(_command(command_type, project_id=project_id, agent=agent), application.uow)
            )
            await asyncio.wait_for(locked.wait(), timeout=2)
            archive_task = asyncio.create_task(
                CredentialService(archive_db, audit_actor=CredentialAuditActor.system("test")).archive(
                    credential.id, project_id=project_id
                )
            )
            await asyncio.sleep(0.1)
            assert not archive_task.done()
            release.set()
            session, archive_result = await asyncio.gather(
                create_task,
                archive_task,
                return_exceptions=True,
            )
            assert isinstance(session, JoySafeterSession)
            assert isinstance(archive_result, AppError)
            assert archive_result.code == "CREDENTIAL_IN_USE"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_snapshot_create_serializes_against_group_archive(
    db_session: AsyncSession,
    postgres_url: str,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    agent = await _agent(db_session, project_id)
    group = await _group(db_session, project_id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    locked, release = asyncio.Event(), asyncio.Event()
    try:
        async with factory() as create_db, factory() as archive_db:
            application = compose_credential_application(
                create_db,
                audit_actor=CredentialAuditActor.system("test"),
                auto_commit=False,
            )
            await _pause_after_locked_source(application, locked, release)
            create_task = asyncio.create_task(
                create(
                    _command(command_type, project_id=project_id, agent=agent, group_ids=(group.id,)),
                    application.uow,
                )
            )
            await asyncio.wait_for(locked.wait(), timeout=2)
            archive_task = asyncio.create_task(
                CredentialGroupService(archive_db, audit_actor=CredentialAuditActor.system("test")).archive(
                    group.id, project_id=project_id
                )
            )
            await asyncio.sleep(0.1)
            assert not archive_task.done()
            release.set()
            session, archive_result = await asyncio.gather(
                create_task,
                archive_task,
                return_exceptions=True,
            )
            assert isinstance(session, JoySafeterSession)
            assert isinstance(archive_result, AppError)
            assert archive_result.code == "CREDENTIAL_IN_USE"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_group_member_mutation_cannot_cross_session_snapshot_boundary(
    db_session: AsyncSession,
    postgres_url: str,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    server_url = "https://mcp.example.com/sse"
    agent = await _agent(
        db_session,
        project_id,
        mcp_servers=[
            {
                "type": "streamable_http",
                "name": "linearized",
                "url": server_url,
                "auth_requirement": "optional",
            }
        ],
    )
    group = await _group(db_session, project_id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    locked, release = asyncio.Event(), asyncio.Event()
    try:
        async with factory() as create_db, factory() as mutate_db:
            application = compose_credential_application(
                create_db,
                audit_actor=CredentialAuditActor.system("test"),
                auto_commit=False,
            )
            await _pause_after_locked_source(application, locked, release)
            create_task = asyncio.create_task(
                create(
                    _command(command_type, project_id=project_id, agent=agent, group_ids=(group.id,)),
                    application.uow,
                )
            )
            await asyncio.wait_for(locked.wait(), timeout=2)
            mutation_task = asyncio.create_task(
                CredentialGroupService(mutate_db, audit_actor=CredentialAuditActor.system("test")).add_credential(
                    group.id,
                    AddGroupCredentialRequest(
                        name=f"racing-member-{uuid.uuid4()}",
                        mcp_server_url=server_url,
                        data={"token_value": "secret"},
                    ),
                    project_id=project_id,
                )
            )
            await asyncio.sleep(0.1)
            assert not mutation_task.done()
            release.set()
            session, mutation_result = await asyncio.gather(
                create_task,
                mutation_task,
                return_exceptions=True,
            )
            assert isinstance(session, JoySafeterSession)
            assert isinstance(mutation_result, AppError)
            assert mutation_result.code == "CREDENTIAL_GROUP_URL_CONFLICT"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_prelock_references_retry_and_persist_reread_snapshot(
    db_session: AsyncSession,
    postgres_url: str,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    first = await _model_credential(db_session, project_id)
    second = await _model_credential(db_session, project_id)
    agent = await _agent(db_session, project_id, model_credential_id=first.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    preloaded, release = asyncio.Event(), asyncio.Event()
    try:
        async with factory() as create_db, factory() as mutate_db:
            application = compose_credential_application(
                create_db,
                audit_actor=CredentialAuditActor.system("test"),
                auto_commit=False,
            )
            original = application.uow.sources.load
            pre_reads = 0

            async def paused(command, *, for_update=False):
                nonlocal pre_reads
                source = await original(command, for_update=for_update)
                if not for_update:
                    pre_reads += 1
                    if pre_reads == 1:
                        preloaded.set()
                        await release.wait()
                return source

            application.uow.sources.load = paused
            create_task = asyncio.create_task(
                create(_command(command_type, project_id=project_id, agent=agent), application.uow)
            )
            await asyncio.wait_for(preloaded.wait(), timeout=2)
            await mutate_db.execute(
                update(JoySafeterAgent)
                .where(JoySafeterAgent.id == agent.id)
                .values(
                    model_credential_id=second.id,
                    version=JoySafeterAgent.version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await mutate_db.commit()
            release.set()
            session = await create_task

            assert pre_reads == 2
            assert session.agent_snapshot["model_credential_id"] == str(second.id)
            assert session.agent_version == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_unrelated_agent_metadata_churn_uses_locked_source_without_retry(
    db_session: AsyncSession,
    postgres_url: str,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    credential = await _model_credential(db_session, project_id)
    agent = await _agent(db_session, project_id, model_credential_id=credential.id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    preloaded, release = asyncio.Event(), asyncio.Event()
    try:
        async with factory() as create_db, factory() as mutate_db:
            application = compose_credential_application(
                create_db,
                audit_actor=CredentialAuditActor.system("test"),
                auto_commit=False,
            )
            original = application.uow.sources.load
            pre_reads = 0

            async def paused(command, *, for_update=False):
                nonlocal pre_reads
                source = await original(command, for_update=for_update)
                if not for_update:
                    pre_reads += 1
                    if pre_reads == 1:
                        preloaded.set()
                        await release.wait()
                return source

            application.uow.sources.load = paused
            create_task = asyncio.create_task(
                create(_command(command_type, project_id=project_id, agent=agent), application.uow)
            )
            await asyncio.wait_for(preloaded.wait(), timeout=2)
            await mutate_db.execute(
                update(JoySafeterAgent)
                .where(JoySafeterAgent.id == agent.id)
                .values(
                    name="metadata-only-rename",
                    version=JoySafeterAgent.version + 1,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            await mutate_db.commit()
            release.set()
            session = await create_task

            assert pre_reads == 1
            assert session.agent_snapshot["name"] == "metadata-only-rename"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_refresh_failure_rolls_back_before_snapshot_commit(
    db_session: AsyncSession,
    project_id: str,
) -> None:
    command_type, create = _snapshot_api()
    agent = await _agent(db_session, project_id)
    application = compose_credential_application(
        db_session,
        audit_actor=CredentialAuditActor.system("test"),
        auto_commit=False,
    )

    async def fail_refresh(_session):
        raise RuntimeError("injected refresh failure")

    application.uow.sessions.refresh = fail_refresh
    with pytest.raises(RuntimeError, match="injected refresh failure"):
        await create(_command(command_type, project_id=project_id, agent=agent), application.uow)

    count = await db_session.scalar(select(func.count()).select_from(JoySafeterSession))
    assert count == 0
