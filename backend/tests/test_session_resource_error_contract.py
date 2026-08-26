import uuid
from datetime import timedelta

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import func, select, text

from app.joysafeter_api.api.v1.sessions import (
    UpdateRepoResourceRequest,
    add_session_resource,
    create_session,
    delete_session_resource,
    list_session_resources,
    update_repo_resource_token,
)
from app.joysafeter_application.credentials.composition import compose_repository_access_material_adapter
from app.joysafeter_application.sessions.resource_service import SessionResourceService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_file import JoySafeterFile
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterMemoryStore, JoySafeterSessionMemoryStore
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_domain.schemas.joysafeter_session import (
    AgentRef,
    CreateSessionRequest,
    SessionFileResourceRequest,
    SessionRepoResourceRequest,
    SessionResourceRequest,
)
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.ids import (
    AgentId,
    AgentVersionId,
    EnvironmentId,
    FileId,
    MemoryStoreId,
    OrganizationId,
    ProjectId,
    SessionId,
    SessionResourceId,
    UserId,
    as_uuid,
)
from app.joysafeter_shared.utils.datetime import utc_now

TEST_USER_ID = UserId.new()
TEST_ORG_ID = OrganizationId.new()


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=TEST_USER_ID,
        org_id=TEST_ORG_ID,
        project_id=None,
        role=JoySafeterRole.MEMBER,
    )


def _project_auth_ctx(project_id: ProjectId, org_id: OrganizationId = TEST_ORG_ID) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=TEST_USER_ID,
        org_id=org_id,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


async def _create_agent(db_session) -> JoySafeterAgent:
    agent = JoySafeterAgent(id=AgentId.new(), name=f"resource-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


async def _create_project_agent(db_session, name: str) -> tuple[Project, JoySafeterAgent]:
    org = Organization(
        id=OrganizationId.new(),
        name=f"{name} Org",
        slug=f"{name.lower()}-org-{uuid.uuid4()}",
    )
    project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4()}",
    )
    db_session.add_all([org, project])
    await db_session.commit()
    agent = JoySafeterAgent(id=AgentId.new(), name=f"{name.lower()}-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(agent)
    return project, agent


async def _create_session(db_session) -> JoySafeterSession:
    agent = await _create_agent(db_session)
    session = JoySafeterSession(id=SessionId.new(), agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _create_file(db_session, project_id: ProjectId, filename: str) -> JoySafeterFile:
    file = JoySafeterFile(
        id=FileId.new(),
        project_id=project_id,
        filename=filename,
        purpose="user_upload",
        content_type="text/plain",
        size_bytes=len(filename),
        sha256="0" * 64,
        storage_key=f"files/{project_id}/{uuid.uuid4()}_{filename}",
        downloadable=False,
    )
    db_session.add(file)
    await db_session.commit()
    await db_session.refresh(file)
    return file


async def _create_project_session(db_session, name: str) -> tuple[Project, JoySafeterSession]:
    org = Organization(
        id=OrganizationId.new(),
        name=f"{name} Org",
        slug=f"{name.lower()}-org-{uuid.uuid4()}",
    )
    project = Project(
        id=ProjectId.new(),
        org_id=org.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4()}",
    )
    db_session.add_all([org, project])
    await db_session.commit()
    agent = JoySafeterAgent(id=AgentId.new(), name=f"{name.lower()}-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(id=SessionId.new(), agent_id=agent.id, project_id=project.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(project)
    await db_session.refresh(session)
    return project, session


async def _session_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(JoySafeterSession))).scalar_one()


@pytest.mark.asyncio
async def test_create_session_missing_memory_store_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    missing_store_id = MemoryStoreId.new()
    req = CreateSessionRequest(
        agent_id=agent.id,
        resources=[SessionResourceRequest(memory_store_id=missing_store_id)],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_MEMORY_STORE_NOT_FOUND",
        "message": f"Memory store not found: {missing_store_id}",
        "data": {"memory_store_id": str(missing_store_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_duplicate_memory_store_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    store = JoySafeterMemoryStore(id=MemoryStoreId.new(), name=f"duplicate-memory-{uuid.uuid4()}", description="")
    db_session.add(store)
    await db_session.commit()
    await db_session.refresh(store)

    req = CreateSessionRequest(
        agent_id=agent.id,
        resources=[
            SessionResourceRequest(memory_store_id=store.id, mount_name="memory-a"),
            SessionResourceRequest(memory_store_id=store.id, mount_name="memory-b"),
        ],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_MEMORY_STORE_ALREADY_ATTACHED",
        "message": f"Memory store is already attached to session: {store.id}",
        "data": {"memory_store_id": str(store.id)},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_session_service_rejects_direct_memory_attach_for_running_session(db_session):
    session = await _create_session(db_session)
    session.status = "running"
    store = JoySafeterMemoryStore(id=MemoryStoreId.new(), name=f"running-memory-{uuid.uuid4()}", description="")
    db_session.add(store)
    await db_session.commit()
    await db_session.refresh(store)

    with pytest.raises(AppError) as exc_info:
        await SessionService(db_session).attach_memory_stores(
            session.id,
            [{"memory_store_id": store.id, "mount_name": "running-memory"}],
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ALREADY_RUNNING",
        "message": "Session resources can only be changed while the session is idle",
        "data": {"session_id": str(session.id), "session_status": "running"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    mounts = (
        (
            await db_session.execute(
                select(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert mounts == []


@pytest.mark.asyncio
async def test_session_service_rejects_direct_archived_memory_store_attach(db_session):
    session = await _create_session(db_session)
    store = JoySafeterMemoryStore(
        id=MemoryStoreId.new(),
        name=f"archived-memory-{uuid.uuid4()}",
        description="",
        archived_at=utc_now(),
    )
    db_session.add(store)
    await db_session.commit()
    await db_session.refresh(store)

    with pytest.raises(AppError) as exc_info:
        await SessionService(db_session).attach_memory_stores(
            session.id,
            [{"memory_store_id": store.id, "mount_name": "archived-memory"}],
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_MEMORY_STORE_ARCHIVED",
        "message": f"Memory store is archived: {store.id}",
        "data": {"memory_store_id": str(store.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    mounts = (
        (
            await db_session.execute(
                select(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert mounts == []


@pytest.mark.asyncio
async def test_session_service_rejects_batch_memory_attach_atomically_when_later_store_archived(db_session):
    session = await _create_session(db_session)
    active_store = JoySafeterMemoryStore(
        id=MemoryStoreId.new(),
        name=f"active-memory-{uuid.uuid4()}",
        description="",
    )
    db_session.add(active_store)
    await db_session.commit()
    await db_session.refresh(active_store)

    archived_store = JoySafeterMemoryStore(
        id=MemoryStoreId.new(),
        name=f"archived-memory-{uuid.uuid4()}",
        description="",
        archived_at=utc_now(),
    )
    db_session.add(archived_store)
    await db_session.commit()
    await db_session.refresh(archived_store)

    with pytest.raises(AppError) as exc_info:
        await SessionService(db_session).attach_memory_stores(
            session.id,
            [
                {"memory_store_id": active_store.id, "mount_name": "active-memory"},
                {"memory_store_id": archived_store.id, "mount_name": "archived-memory"},
            ],
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_MEMORY_STORE_ARCHIVED",
        "message": f"Memory store is archived: {archived_store.id}",
        "data": {"memory_store_id": str(archived_store.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    mounts = (
        (
            await db_session.execute(
                select(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert mounts == []


@pytest.mark.asyncio
async def test_session_service_rejects_duplicate_memory_attach_before_unique_constraint(db_session):
    session = await _create_session(db_session)
    store = JoySafeterMemoryStore(id=MemoryStoreId.new(), name=f"duplicate-memory-{uuid.uuid4()}", description="")
    db_session.add(store)
    await db_session.commit()
    await db_session.refresh(store)

    await SessionService(db_session).attach_memory_stores(
        session.id,
        [{"memory_store_id": store.id, "mount_name": "memory"}],
    )

    with pytest.raises(AppError) as exc_info:
        await SessionService(db_session).attach_memory_stores(
            session.id,
            [{"memory_store_id": store.id, "mount_name": "memory-again"}],
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_MEMORY_STORE_ALREADY_ATTACHED",
        "message": f"Memory store is already attached to session: {store.id}",
        "data": {"session_id": str(session.id), "memory_store_id": str(store.id)},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    mounts = (
        (
            await db_session.execute(
                select(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(mounts) == 1
    assert mounts[0].store_id == store.id


@pytest.mark.asyncio
async def test_create_session_missing_file_resource_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    missing_file_id = FileId.new()
    req = CreateSessionRequest(
        agent_id=agent.id,
        file_resources=[SessionFileResourceRequest(file_id=missing_file_id)],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_FILE_NOT_FOUND",
        "message": f"File not found: {missing_file_id}",
        "data": {"file_id": str(missing_file_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_duplicate_file_mount_path_returns_structured_error_without_creating_session(db_session):
    project, agent = await _create_project_agent(db_session, "FileMountConflictCreate")
    first_file = await _create_file(db_session, project.id, "first.txt")
    second_file = await _create_file(db_session, project.id, "second.txt")
    req = CreateSessionRequest(
        agent_id=agent.id,
        file_resources=[
            SessionFileResourceRequest(file_id=first_file.id, mount_path="/workspace/shared.txt"),
            SessionFileResourceRequest(file_id=second_file.id, mount_path="/workspace/dir/../shared.txt"),
        ],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _project_auth_ctx(project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_FILE_MOUNT_PATH_CONFLICT",
        "message": "File mount_path is already used by another session file resource: /workspace/shared.txt",
        "data": {"mount_path": "/workspace/shared.txt", "file_id": str(second_file.id)},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_invalid_repo_resource_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    req = CreateSessionRequest(
        agent_id=agent.id,
        repo_resources=[SessionRepoResourceRequest(url=" ")],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SESSION_REPO_URL_REQUIRED",
        "message": "repo resource url is required",
        "data": {"resource_type": "github_repository"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_duplicate_repo_effective_mount_path_returns_structured_error_without_creating_session(
    db_session,
):
    project, agent = await _create_project_agent(db_session, "RepoMountConflictCreate")
    req = CreateSessionRequest(
        agent_id=agent.id,
        repo_resources=[
            SessionRepoResourceRequest(url="https://github.com/acme/api.git"),
            SessionRepoResourceRequest(url="git@github.com:other/api.git"),
        ],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _project_auth_ctx(project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_REPO_MOUNT_PATH_CONFLICT",
        "message": "Repo effective mount_path is already used by another session repo resource: /workspace/api",
        "data": {"mount_path": "/workspace/api", "url": "git@github.com:other/api.git"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_file_and_repo_share_workspace_namespace_without_creating_session(db_session):
    project, agent = await _create_project_agent(db_session, "CrossMountConflictCreate")
    file = await _create_file(db_session, project.id, "api")
    req = CreateSessionRequest(
        agent_id=agent.id,
        file_resources=[SessionFileResourceRequest(file_id=file.id)],
        repo_resources=[SessionRepoResourceRequest(url="https://github.com/acme/api.git")],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _project_auth_ctx(project.id))

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_RESOURCE_MOUNT_PATH_CONFLICT",
        "message": "Session resource mount_path is already used: /workspace/api",
        "data": {"mount_path": "/workspace/api", "resource_type": "github_repository"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_session_repo_resources_keep_token_encrypted_and_never_echoed(db_session):
    agent = await _create_agent(db_session)
    response = await create_session(
        CreateSessionRequest(
            agent_id=agent.id,
            repo_resources=[
                SessionRepoResourceRequest(
                    url="https://github.com/example/private-repo.git",
                    branch="main",
                    mount_path="/workspace/private-repo",
                    authorization_token="initial-token",
                )
            ],
        ),
        db_session,
        _auth_ctx(),
    )

    stored = (
        await db_session.execute(select(JoySafeterSessionRepo).where(JoySafeterSessionRepo.session_id == response.id))
    ).scalar_one()
    repo_id = stored.id
    assert stored.encrypted_token.startswith("enc:")
    assert stored.encrypted_token != "initial-token"
    initial_encrypted_token = stored.encrypted_token
    assert "initial-token" not in response.model_dump_json()

    listed = await list_session_resources(response.id, _auth_ctx(), db_session)
    assert "initial-token" not in str(listed)
    assert "encrypted_token" not in str(listed)

    await update_repo_resource_token(
        response.id,
        repo_id,
        UpdateRepoResourceRequest(authorization_token="rotated-token"),
        _auth_ctx(),
        db_session,
    )

    db_session.expire_all()
    rotated = (
        await db_session.execute(select(JoySafeterSessionRepo).where(JoySafeterSessionRepo.id == repo_id))
    ).scalar_one()
    assert rotated.encrypted_token.startswith("enc:")
    assert rotated.encrypted_token != "rotated-token"
    assert rotated.encrypted_token != initial_encrypted_token


@pytest.mark.asyncio
async def test_repository_token_is_erased_when_session_becomes_terminal(db_session):
    session = await _create_session(db_session)
    repo = JoySafeterSessionRepo(
        id=SessionResourceId.new(),
        session_id=session.id,
        url="https://github.com/example/private-repo.git",
        branch="main",
        mount_path="/workspace/private-repo",
        mount_name="private-repo",
        encrypted_token="enc:v1:terminal-secret",
    )
    db_session.add(repo)
    await db_session.commit()

    transitioned = await SessionService(db_session).update_session_status(session.id, "terminated")

    assert transitioned is True
    row = (
        await db_session.execute(
            text(
                """
                SELECT encrypted_token, token_erased_at
                FROM joysafeter_session_repos
                WHERE id = :repo_id
                """
            ),
            {"repo_id": as_uuid(repo.id)},
        )
    ).one()
    assert row.encrypted_token == ""
    assert row.token_erased_at is not None


@pytest.mark.asyncio
async def test_repository_token_rotation_records_expiry_and_rotation_metadata(db_session):
    session = await _create_session(db_session)
    repo = JoySafeterSessionRepo(
        id=SessionResourceId.new(),
        session_id=session.id,
        url="https://github.com/example/private-repo.git",
        branch="main",
        mount_path="/workspace/private-repo",
        mount_name="private-repo",
        encrypted_token="",
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    expires_at = utc_now() + timedelta(hours=1)

    await SessionResourceService(db_session).rotate_repo_token(
        session.id,
        repo.id,
        "rotated-token",
        token_expires_at=expires_at,
    )

    row = (
        await db_session.execute(
            text(
                """
                SELECT encrypted_token, token_expires_at, token_rotated_at, token_erased_at
                FROM joysafeter_session_repos
                WHERE id = :repo_id
                """
            ),
            {"repo_id": as_uuid(repo.id)},
        )
    ).one()
    assert row.encrypted_token.startswith("enc:")
    assert row.token_expires_at == expires_at
    assert row.token_rotated_at is not None
    assert row.token_erased_at is None


@pytest.mark.asyncio
async def test_session_resource_service_keeps_parent_project_boundary_for_repo_children(db_session):
    material = compose_repository_access_material_adapter(joysafeter_config.vault_encryption_key)
    project, session = await _create_project_session(db_session, "SessionResourceSvcProject")
    other_project, _ = await _create_project_session(db_session, "SessionResourceSvcOtherProject")
    project_id = project.id
    other_project_id = other_project.id
    row = JoySafeterSessionRepo(
        id=SessionResourceId.new(),
        session_id=session.id,
        url="https://github.com/acme/private",
        branch="main",
        mount_name="private",
        mount_path="/workspace/private",
        encrypted_token=material.protect_repository_token("old-token"),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    session_id = session.id
    resource_id = row.id
    raw_row_id = row.id
    svc = SessionResourceService(db_session)

    assert await svc.list_resources(session_id, project_id=other_project_id) == []

    with pytest.raises(AppError) as exc_info:
        await svc.rotate_repo_token(
            session_id,
            resource_id,
            "new-token",
            project_id=other_project_id,
        )
    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_REPO_RESOURCE_NOT_FOUND",
        "message": "Repo resource not found",
        "data": {"session_id": str(session_id), "resource_id": str(resource_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    with pytest.raises(AppError) as exc_info:
        await svc.delete_resource(session_id, resource_id, project_id=other_project_id)
    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_RESOURCE_NOT_FOUND",
        "message": "Resource not found",
        "data": {"session_id": str(session_id), "resource_id": str(resource_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    db_session.expire_all()
    kept = (
        await db_session.execute(select(JoySafeterSessionRepo).where(JoySafeterSessionRepo.id == raw_row_id))
    ).scalar_one()
    assert kept.session_id == session_id
    assert kept.url == "https://github.com/acme/private"
    assert other_project_id != project_id


@pytest.mark.asyncio
async def test_create_session_missing_environment_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    environment_id = EnvironmentId.new()
    req = CreateSessionRequest(agent_id=agent.id, environment_id=environment_id)

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SESSION_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {environment_id}",
        "data": {"environment_id": str(environment_id)},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_archived_environment_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    env = JoySafeterEnvironment(
        id=EnvironmentId.new(),
        name=f"archived-session-env-{uuid.uuid4()}",
        description="",
        archived_at=utc_now(),
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)

    environment_id = env.id
    req = CreateSessionRequest(agent_id=agent.id, environment_id=environment_id)

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: {environment_id}",
        "data": {"environment_id": str(environment_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_pinned_agent_version_uses_snapshot_environment(db_session):
    pinned_env = JoySafeterEnvironment(
        id=EnvironmentId.new(),
        name=f"pinned-env-{uuid.uuid4()}",
        description="",
        config={"env_vars": {"PINNED": "1"}},
        image_tag="pinned-image:1",
        image_version=1,
    )
    live_env = JoySafeterEnvironment(
        id=EnvironmentId.new(),
        name=f"live-env-{uuid.uuid4()}",
        description="",
        config={"env_vars": {"LIVE": "1"}},
        image_tag="live-image:2",
        image_version=2,
    )
    db_session.add(pinned_env)
    await db_session.commit()
    await db_session.refresh(pinned_env)
    db_session.add(live_env)
    await db_session.commit()
    await db_session.refresh(live_env)

    agent = JoySafeterAgent(
        id=AgentId.new(),
        name=f"pinned-session-agent-{uuid.uuid4()}",
        version=2,
        environment_id=live_env.id,
    )
    db_session.add(agent)
    await db_session.flush()
    pinned_ref = str(pinned_env.id)
    db_session.add(
        JoySafeterAgentVersion(
            id=AgentVersionId.new(),
            agent_id=agent.id,
            version=1,
            snapshot={
                "schema": "joysafeter.agent_execution_snapshot.v2",
                "id": str(agent.id),
                "version": 1,
                "name": agent.name,
                "engine_kind": "claude",
                "model": {"id": "pinned-model"},
                "skills": [],
                "agents": [],
                "commands": [],
                "tools": [],
                "mcp_servers": [],
                "environment_id": pinned_ref,
            },
        )
    )
    await db_session.commit()
    await db_session.refresh(agent)

    response = await create_session(
        CreateSessionRequest(agent=AgentRef(id=agent.id, version=1)),
        db_session,
        _auth_ctx(),
    )

    row = (await db_session.execute(select(JoySafeterSession).where(JoySafeterSession.id == response.id))).scalar_one()
    assert row.agent_version == 1
    assert row.environment_id == pinned_env.id
    assert row.agent_snapshot["environment_id"] == pinned_ref
    assert row.agent_snapshot["environment"]["image_tag"] == "pinned-image:1"
    assert row.agent_snapshot["environment"]["config"]["env_vars"] == {"PINNED": "1"}


@pytest.mark.asyncio
async def test_create_session_archived_agent_returns_structured_error_without_creating_session(db_session):
    agent = JoySafeterAgent(id=AgentId.new(), name=f"archived-session-agent-{uuid.uuid4()}", archived_at=utc_now())
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    req = CreateSessionRequest(agent_id=agent.id)

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "AGENT_ARCHIVED",
        "message": "Agent is archived and cannot create new sessions.",
        "data": {"agent_id": str(agent.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_add_session_resource_rejects_non_object_body_with_structured_error(db_session):
    session = await _create_session(db_session)

    with pytest.raises(AppError) as exc_info:
        await add_session_resource(session.id, [], _auth_ctx(), db_session)  # type: ignore[arg-type]

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SESSION_RESOURCE_BODY_INVALID",
        "message": "Request body must be an object",
        "data": {"expected": "object"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_add_session_resource_missing_file_returns_structured_error(db_session):
    session = await _create_session(db_session)
    missing_file_id = FileId.new()

    with pytest.raises(AppError) as exc_info:
        await add_session_resource(session.id, {"type": "file", "file_id": missing_file_id}, _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_FILE_NOT_FOUND",
        "message": f"File not found: {missing_file_id}",
        "data": {"session_id": str(session.id), "file_id": str(missing_file_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_session_resource_service_rejects_file_mount_path_collision_before_insert(db_session):
    project, session = await _create_project_session(db_session, "FileMountConflictDirect")
    first_file = await _create_file(db_session, project.id, "first.txt")
    second_file = await _create_file(db_session, project.id, "second.txt")
    svc = SessionResourceService(db_session)

    await svc.add_file_resource(
        session.id,
        SessionFileResourceRequest(file_id=first_file.id, mount_path="/workspace/shared.txt"),
        project_id=project.id,
    )

    with pytest.raises(AppError) as exc_info:
        await svc.add_file_resource(
            session.id,
            SessionFileResourceRequest(file_id=second_file.id, mount_path="/workspace/./shared.txt"),
            project_id=project.id,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_FILE_MOUNT_PATH_CONFLICT",
        "message": "File mount_path is already used by another session file resource: /workspace/shared.txt",
        "data": {
            "session_id": str(session.id),
            "mount_path": "/workspace/shared.txt",
            "file_id": str(second_file.id),
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    mounts = (
        (await db_session.execute(select(JoySafeterSessionFile).where(JoySafeterSessionFile.session_id == session.id)))
        .scalars()
        .all()
    )
    assert len(mounts) == 1
    assert mounts[0].file_id == first_file.id
    assert mounts[0].mount_path == "/workspace/shared.txt"


@pytest.mark.asyncio
async def test_add_session_resource_rejects_running_session_before_resource_lookup(db_session):
    session = await _create_session(db_session)
    session.status = "running"
    await db_session.commit()
    missing_file_id = FileId.new()

    with pytest.raises(AppError) as exc_info:
        await add_session_resource(session.id, {"type": "file", "file_id": missing_file_id}, _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ALREADY_RUNNING",
        "message": "Session resources can only be changed while the session is idle",
        "data": {"session_id": str(session.id), "session_status": "running"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }


@pytest.mark.asyncio
async def test_session_resource_service_rejects_direct_repo_add_for_running_session(db_session):
    session = await _create_session(db_session)
    session.status = "running"
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await SessionResourceService(db_session).add_repo_resource(
            session.id,
            SessionRepoResourceRequest(url="https://github.com/example/repo"),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ALREADY_RUNNING",
        "message": "Session resources can only be changed while the session is idle",
        "data": {"session_id": str(session.id), "session_status": "running"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }
    count = (
        await db_session.execute(
            select(func.count())
            .select_from(JoySafeterSessionRepo)
            .where(JoySafeterSessionRepo.session_id == session.id)
        )
    ).scalar_one()
    assert count == 0


@pytest.mark.asyncio
async def test_session_resource_service_rejects_repo_effective_mount_path_collision_before_insert(db_session):
    project, session = await _create_project_session(db_session, "RepoMountConflictDirect")
    svc = SessionResourceService(db_session)

    await svc.add_repo_resource(
        session.id,
        SessionRepoResourceRequest(url="https://github.com/acme/api.git"),
        project_id=project.id,
    )

    with pytest.raises(AppError) as exc_info:
        await svc.add_repo_resource(
            session.id,
            SessionRepoResourceRequest(url="https://github.com/other/api.git", mount_path="/workspace/./api"),
            project_id=project.id,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_REPO_MOUNT_PATH_CONFLICT",
        "message": "Repo effective mount_path is already used by another session repo resource: /workspace/api",
        "data": {
            "session_id": str(session.id),
            "mount_path": "/workspace/api",
            "url": "https://github.com/other/api.git",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    repos = (
        (await db_session.execute(select(JoySafeterSessionRepo).where(JoySafeterSessionRepo.session_id == session.id)))
        .scalars()
        .all()
    )
    assert len(repos) == 1
    assert repos[0].url == "https://github.com/acme/api.git"
    assert repos[0].mount_path == ""


@pytest.mark.asyncio
async def test_session_resource_service_rejects_repo_file_mount_path_collision_before_insert(db_session):
    project, session = await _create_project_session(db_session, "CrossMountConflictDirect")
    file = await _create_file(db_session, project.id, "api")
    svc = SessionResourceService(db_session)

    await svc.add_file_resource(
        session.id,
        SessionFileResourceRequest(file_id=file.id),
        project_id=project.id,
    )

    with pytest.raises(AppError) as exc_info:
        await svc.add_repo_resource(
            session.id,
            SessionRepoResourceRequest(url="https://github.com/acme/api.git"),
            project_id=project.id,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_RESOURCE_MOUNT_PATH_CONFLICT",
        "message": "Session resource mount_path is already used: /workspace/api",
        "data": {
            "session_id": str(session.id),
            "mount_path": "/workspace/api",
            "resource_type": "github_repository",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    repos = (
        (await db_session.execute(select(JoySafeterSessionRepo).where(JoySafeterSessionRepo.session_id == session.id)))
        .scalars()
        .all()
    )
    assert repos == []


@pytest.mark.asyncio
async def test_delete_session_resource_rejects_archived_session_before_resource_lookup(db_session):
    session = await _create_session(db_session)
    session.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await delete_session_resource(session.id, SessionResourceId.new(), _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ARCHIVED",
        "message": "Session is archived",
        "data": {"session_id": str(session.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_rotate_repo_resource_rejects_running_session_without_mutating_token(db_session):
    session = await _create_session(db_session)
    repo = JoySafeterSessionRepo(
        id=SessionResourceId.new(),
        session_id=session.id,
        url="https://github.com/example/repo",
        branch="main",
        mount_path="/workspace/repo",
        mount_name="repo",
        encrypted_token="old-token-ciphertext",
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    repo_id = repo.id

    session.status = "running"
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await update_repo_resource_token(
            session.id,
            repo_id,
            UpdateRepoResourceRequest(authorization_token="new-token"),
            _auth_ctx(),
            db_session,
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ALREADY_RUNNING",
        "message": "Session resources can only be changed while the session is idle",
        "data": {"session_id": str(session.id), "session_status": "running"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterSessionRepo).where(JoySafeterSessionRepo.id == repo_id))
    ).scalar_one()
    assert row.encrypted_token == "old-token-ciphertext"


@pytest.mark.asyncio
async def test_session_resource_service_rejects_direct_repo_mutations_for_running_session(db_session):
    session = await _create_session(db_session)
    repo = JoySafeterSessionRepo(
        id=SessionResourceId.new(),
        session_id=session.id,
        url="https://github.com/example/repo",
        branch="main",
        mount_path="/workspace/repo",
        mount_name="repo",
        encrypted_token="old-token-ciphertext",
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)
    repo_id = repo.id

    session.status = "running"
    await db_session.commit()
    svc = SessionResourceService(db_session)

    with pytest.raises(AppError) as exc_info:
        await svc.rotate_repo_token(session.id, f"sesrsc_{repo_id}", "new-token")

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ALREADY_RUNNING",
        "message": "Session resources can only be changed while the session is idle",
        "data": {"session_id": str(session.id), "session_status": "running"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    with pytest.raises(AppError) as exc_info:
        await svc.delete_resource(session.id, f"sesrsc_{repo_id}")

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_ALREADY_RUNNING",
        "message": "Session resources can only be changed while the session is idle",
        "data": {"session_id": str(session.id), "session_status": "running"},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    row = (
        await db_session.execute(select(JoySafeterSessionRepo).where(JoySafeterSessionRepo.id == repo_id))
    ).scalar_one()
    assert row.encrypted_token == "old-token-ciphertext"
