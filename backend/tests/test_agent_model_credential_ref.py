"""Service-level tests for Task 9a: Agent references its model connection by a
stable ``model_credential_id`` FK (was name-based ``secret_ref``).

Real-DB tests via conftest's ``db_session``: the FK to ``joysafeter_credentials``
and the CredentialService kind check are enforced against Postgres. The full app
is intentionally un-loadable mid-cutover, so everything here runs at the
service/model level (no TestClient).
"""

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterEngineKind,
)
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_api.api.v1.agents import _agent_to_response
from app.joysafeter_api.api.v1.model_connection_summary import load_model_connection_summaries
from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import SqlAlchemyCredentialRepository
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import CredentialId


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


async def _make_model_credential(
    db_session,
    project_id: str,
    *,
    provider: str = "anthropic",
    protocol: str = "anthropic_messages",
    model: str | None = None,
) -> CredentialId:
    data = {"API_KEY": "sk-secret"}
    if model:
        data["ANTHROPIC_MODEL" if provider == "anthropic" else "OPENAI_MODEL"] = model
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="model",
            name=f"m-{uuid.uuid4()}",
            provider=provider,
            protocol=protocol,
            data=data,
        ),
        project_id=project_id,
    )
    return cred.id


async def _make_service_credential(db_session, project_id: str) -> CredentialId:
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(kind="service", name=f"s-{uuid.uuid4()}", data={"TOKEN": "t"}),
        project_id=project_id,
    )
    return cred.id


def _create_req(model_credential_id: CredentialId | None) -> JoySafeterCreateAgentRequest:
    return JoySafeterCreateAgentRequest(
        name=f"agent-{uuid.uuid4()}",
        engine_kind=JoySafeterEngineKind.CLAUDE,
        model_credential_id=model_credential_id,
    )


@pytest.mark.asyncio
async def test_create_agent_persists_model_credential_id(db_session, project_id):
    cred_id = await _make_model_credential(db_session, project_id)
    svc = JoySafeterAgentService(db_session)

    agent = await svc.create_agent(_create_req(cred_id), project_id=project_id)

    assert agent.model_credential_id == cred_id
    # The agent-version snapshot embeds the id (not a name/secret_ref).
    snapshot = agent.versions[0].snapshot
    assert snapshot["model_credential_id"] == str(cred_id)
    assert "secret_ref" not in snapshot


@pytest.mark.asyncio
async def test_agent_response_includes_model_connection_summary(db_session, project_id):
    cred_id = await _make_model_credential(db_session, project_id, model="claude-sonnet-4-5")
    svc = JoySafeterAgentService(db_session)

    agent = await svc.create_agent(_create_req(cred_id), project_id=project_id)
    summaries = await load_model_connection_summaries(db_session, [cred_id], project_id=project_id)
    response = _agent_to_response(agent, model_connection=summaries[cred_id])

    assert response.model is None
    assert response.model_credential_id == cred_id
    assert response.model_connection is not None
    assert response.model_connection.id == cred_id
    assert response.model_connection.model == "claude-sonnet-4-5"


@pytest.mark.asyncio
async def test_execution_snapshot_embeds_model_credential_id(db_session, project_id):
    cred_id = await _make_model_credential(db_session, project_id)
    svc = JoySafeterAgentService(db_session)
    agent = await svc.create_agent(_create_req(cred_id), project_id=project_id)

    snapshot = svc.build_execution_snapshot(agent)
    assert snapshot["model_credential_id"] == str(cred_id)
    assert "secret_ref" not in snapshot


@pytest.mark.asyncio
async def test_create_agent_without_model_credential_id(db_session, project_id):
    svc = JoySafeterAgentService(db_session)
    agent = await svc.create_agent(_create_req(None), project_id=project_id)

    assert agent.model_credential_id is None
    assert agent.versions[0].snapshot["model_credential_id"] is None


@pytest.mark.asyncio
async def test_create_agent_with_nonexistent_credential_raises(db_session, project_id):
    svc = JoySafeterAgentService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.create_agent(_create_req(CredentialId.new()), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_agent_with_non_model_credential_raises_kind_invalid(db_session, project_id):
    service_cred_id = await _make_service_credential(db_session, project_id)
    svc = JoySafeterAgentService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.create_agent(_create_req(service_cred_id), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_KIND_INVALID"


@pytest.mark.asyncio
async def test_create_agent_with_credential_from_other_project_raises(db_session, project_id):
    other_project = await _make_project(db_session)
    other_cred_id = await _make_model_credential(db_session, other_project)
    svc = JoySafeterAgentService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.create_agent(_create_req(other_cred_id), project_id=project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_agent_with_archived_credential_raises_state_invalid(db_session, project_id):
    credential_id = await _make_model_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.archived_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await JoySafeterAgentService(db_session).create_agent(
            _create_req(credential_id), project_id=project_id
        )

    assert exc.value.code == "CREDENTIAL_STATE_INVALID"
    assert exc.value.data == {"credential_id": str(credential_id)}


@pytest.mark.asyncio
async def test_create_agent_with_deleted_credential_raises_not_found(db_session, project_id):
    credential_id = await _make_model_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await JoySafeterAgentService(db_session).create_agent(
            _create_req(credential_id), project_id=project_id
        )

    assert exc.value.code == "CREDENTIAL_NOT_FOUND"
    assert exc.value.data == {"credential_id": str(credential_id)}


@pytest.mark.asyncio
async def test_create_agent_rejects_model_protocol_incompatible_with_engine(db_session, project_id):
    credential_id = await _make_model_credential(
        db_session,
        project_id,
        provider="openai",
        protocol="openai_responses",
    )

    with pytest.raises(AppError) as exc:
        await JoySafeterAgentService(db_session).create_agent(
            _create_req(credential_id), project_id=project_id
        )

    assert exc.value.code == "CREDENTIAL_KIND_INVALID"


@pytest.mark.asyncio
async def test_create_agent_rejects_disabled_engine(db_session, project_id, monkeypatch):
    credential_id = await _make_model_credential(db_session, project_id)
    catalog = get_llm_catalog().model_copy(deep=True)
    catalog.engine("claude").enabled = False
    monkeypatch.setattr(
        "app.joysafeter_domain.services.joysafeter_agent_service.get_llm_catalog",
        lambda: catalog,
    )

    with pytest.raises(AppError) as exc:
        await JoySafeterAgentService(db_session).create_agent(
            _create_req(credential_id),
            project_id=project_id,
        )

    assert exc.value.code == "LLM_ENGINE_DISABLED"
    assert exc.value.data == {"engine_kind": "claude"}
    assert exc.value.user_action == "fix_input"


@pytest.mark.asyncio
async def test_archive_serializes_against_concurrent_agent_binding(
    db_session,
    postgres_url,
    project_id,
    monkeypatch,
):
    credential_id = await _make_model_credential(db_session, project_id)
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    archive_scanned = asyncio.Event()
    release_archive = asyncio.Event()
    binding_validated = asyncio.Event()

    try:
        async with session_factory() as archive_db, session_factory() as binding_db:
            credential_service = CredentialService(archive_db)
            original_reject = SqlAlchemyCredentialRepository._reject_if_in_use

            async def pause_after_dependency_scan(repository, credential, scoped_project_id, *, verb):
                await original_reject(repository, credential, scoped_project_id, verb=verb)
                archive_scanned.set()
                await release_archive.wait()

            monkeypatch.setattr(
                SqlAlchemyCredentialRepository,
                "_reject_if_in_use",
                pause_after_dependency_scan,
            )

            agent_service = JoySafeterAgentService(binding_db)
            original_validate = agent_service._validate_model_credential_ref

            async def observe_binding_validation(candidate_id, scoped_project_id):
                await original_validate(candidate_id, scoped_project_id)
                binding_validated.set()

            agent_service._validate_model_credential_ref = observe_binding_validation

            archive_task = asyncio.create_task(
                credential_service.archive(credential_id, project_id=project_id)
            )
            await asyncio.wait_for(archive_scanned.wait(), timeout=2)
            binding_task = asyncio.create_task(
                agent_service.create_agent(_create_req(credential_id), project_id=project_id)
            )

            try:
                await asyncio.wait_for(binding_validated.wait(), timeout=0.25)
                binding_passed_while_archive_was_open = True
            except TimeoutError:
                binding_passed_while_archive_was_open = False

            release_archive.set()
            archive_result, binding_result = await asyncio.gather(
                archive_task,
                binding_task,
                return_exceptions=True,
            )

            assert not isinstance(archive_result, Exception)
            assert binding_passed_while_archive_was_open is False
            assert isinstance(binding_result, AppError)
            assert binding_result.code == "CREDENTIAL_STATE_INVALID"
    finally:
        await engine.dispose()


def test_agent_model_binding_has_no_legacy_credential_inspection() -> None:
    source = (
        Path(__file__).resolve().parents[1] / "app/joysafeter_domain/services/joysafeter_agent_service.py"
    ).read_text()
    assert "build_model_inference_policy" in source
    assert "ModelInferenceBinding(" not in source
    for forbidden in (
        "CredentialService",
        "cred.kind",
        "cred.archived_at",
        "get_credential_data",
        "LegacyV1MaterialProtector",
    ):
        assert forbidden not in source
