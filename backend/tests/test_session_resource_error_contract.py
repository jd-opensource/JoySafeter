import uuid

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import func, select

from app.joysafeter_api.api.v1.sessions import (
    UpdateRepoResourceRequest,
    add_session_resource,
    create_session,
    delete_session_resource,
    list_session_resources,
    update_repo_resource_token,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_domain.models.joysafeter_vault import JoySafeterVault
from app.joysafeter_domain.schemas.joysafeter_session import (
    CreateSessionRequest,
    SessionFileResourceRequest,
    SessionRepoResourceRequest,
    SessionResourceRequest,
)
from app.joysafeter_domain.services.joysafeter_session_resource_service import SessionResourceService
from app.joysafeter_domain.services.joysafeter_vault_cipher import VaultCipher
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.MEMBER,
    )


async def _create_agent(db_session) -> JoySafeterAgent:
    agent = JoySafeterAgent(name=f"resource-agent-{uuid.uuid4()}")
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


async def _create_session(db_session) -> JoySafeterSession:
    agent = await _create_agent(db_session)
    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)
    return session


async def _create_project_session(db_session, name: str) -> tuple[Project, JoySafeterSession]:
    org = Organization(
        id=f"org-{uuid.uuid4()}",
        name=f"{name} Org",
        slug=f"{name.lower()}-org-{uuid.uuid4()}",
    )
    project = Project(
        id=f"proj-{uuid.uuid4()}",
        org_id=org.id,
        name=name,
        slug=f"{name.lower()}-{uuid.uuid4()}",
    )
    db_session.add_all([org, project])
    await db_session.commit()
    agent = JoySafeterAgent(name=f"{name.lower()}-agent-{uuid.uuid4()}", project_id=project.id)
    db_session.add(agent)
    await db_session.flush()
    session = JoySafeterSession(agent_id=agent.id, project_id=project.id, status="idle")
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
    missing_store_id = uuid.uuid4()
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
async def test_create_session_missing_file_resource_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    missing_file_id = f"file_{uuid.uuid4()}"
    req = CreateSessionRequest(
        agent_id=agent.id,
        file_resources=[SessionFileResourceRequest(file_id=missing_file_id)],
    )

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_FILE_NOT_FOUND",
        "message": f"File not found: {missing_file_id}",
        "data": {"file_id": missing_file_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
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
async def test_session_repo_resources_keep_token_encrypted_and_never_echoed(db_session, monkeypatch):
    cipher = VaultCipher(VaultCipher.generate_key())
    monkeypatch.setattr("app.joysafeter_domain.services.joysafeter_secret_service._cipher", cipher)

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
        f"sesrsc_{repo_id}",
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
async def test_session_resource_service_keeps_parent_project_boundary_for_repo_children(db_session, monkeypatch):
    cipher = VaultCipher(VaultCipher.generate_key())
    monkeypatch.setattr("app.joysafeter_domain.services.joysafeter_secret_service._cipher", cipher)
    project, session = await _create_project_session(db_session, "SessionResourceSvcProject")
    other_project, _ = await _create_project_session(db_session, "SessionResourceSvcOtherProject")
    project_id = project.id
    other_project_id = other_project.id
    row = JoySafeterSessionRepo(
        session_id=session.id,
        url="https://github.com/acme/private",
        branch="main",
        mount_name="private",
        mount_path="/workspace/private",
        encrypted_token=cipher.encrypt("old-token"),
    )
    db_session.add(row)
    await db_session.commit()
    await db_session.refresh(row)
    session_id = session.id
    resource_id = f"sesrsc_{row.id}"
    raw_row_id = row.id
    svc = SessionResourceService(db_session)

    assert await svc.list_resource_payloads(session_id, project_id=other_project_id) == []

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
        "data": {"session_id": str(session_id), "resource_id": resource_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }

    with pytest.raises(AppError) as exc_info:
        await svc.delete_resource(session_id, resource_id, project_id=other_project_id)
    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_RESOURCE_NOT_FOUND",
        "message": "Resource not found",
        "data": {"session_id": str(session_id), "resource_id": resource_id},
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
    environment_id = f"env_{uuid.uuid4()}"
    req = CreateSessionRequest(agent_id=agent.id, environment_id=environment_id)

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=422) == {
        "code": "SESSION_ENVIRONMENT_NOT_FOUND",
        "message": f"Environment not found: {environment_id}",
        "data": {"environment_ref": environment_id},
        "source": "validation",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_archived_environment_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    env = JoySafeterEnvironment(
        name=f"archived-session-env-{uuid.uuid4()}",
        description="",
        archived_at=utc_now(),
    )
    db_session.add(env)
    await db_session.commit()
    await db_session.refresh(env)

    environment_id = f"env_{env.id}"
    req = CreateSessionRequest(agent_id=agent.id, environment_id=environment_id)

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "ENVIRONMENT_ARCHIVED",
        "message": f"Environment is archived: {environment_id}",
        "data": {"environment_ref": environment_id, "environment_id": str(env.id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    assert await _session_count(db_session) == 0


@pytest.mark.asyncio
async def test_create_session_archived_agent_returns_structured_error_without_creating_session(db_session):
    agent = JoySafeterAgent(name=f"archived-session-agent-{uuid.uuid4()}", archived_at=utc_now())
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
async def test_create_session_archived_vault_returns_structured_error_without_creating_session(db_session):
    agent = await _create_agent(db_session)
    vault = JoySafeterVault(name=f"archived-session-vault-{uuid.uuid4()}", description="", archived_at=utc_now())
    db_session.add(vault)
    await db_session.commit()
    await db_session.refresh(vault)

    vault_ref = f"vault_{vault.id}"
    req = CreateSessionRequest(agent_id=agent.id, vault_ids=[vault_ref])

    with pytest.raises(AppError) as exc_info:
        await create_session(req, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "SESSION_VAULT_ARCHIVED",
        "message": f"Vault is archived: {vault_ref}",
        "data": {"vault_id": vault_ref},
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
    missing_file_id = f"file_{uuid.uuid4()}"

    with pytest.raises(AppError) as exc_info:
        await add_session_resource(session.id, {"type": "file", "file_id": missing_file_id}, _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "SESSION_FILE_NOT_FOUND",
        "message": f"File not found: {missing_file_id}",
        "data": {"session_id": str(session.id), "file_id": missing_file_id},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }


@pytest.mark.asyncio
async def test_add_session_resource_rejects_running_session_before_resource_lookup(db_session):
    session = await _create_session(db_session)
    session.status = "running"
    await db_session.commit()
    missing_file_id = f"file_{uuid.uuid4()}"

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
async def test_delete_session_resource_invalid_id_returns_structured_error(db_session):
    session = await _create_session(db_session)

    with pytest.raises(AppError) as exc_info:
        await delete_session_resource(session.id, "sesrsc_not-a-uuid", _auth_ctx(), db_session)

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "SESSION_RESOURCE_ID_INVALID",
        "message": "Invalid resource_id",
        "data": {"session_id": str(session.id), "resource_id": "sesrsc_not-a-uuid"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_delete_session_resource_rejects_archived_session_before_resource_lookup(db_session):
    session = await _create_session(db_session)
    session.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await delete_session_resource(session.id, f"sesrsc_{uuid.uuid4()}", _auth_ctx(), db_session)

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
            f"sesrsc_{repo_id}",
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
