"""Error-contract tests for the quickstart model consumer.

The request references a model credential by ``model_credential_id`` and the
endpoint resolves it through canonical ModelInferenceBinding policy/material
ports rather than the CredentialService compatibility facade.

The upstream-event helpers are pure functions; the resolution-path tests use
conftest's real ``db_session`` (the full app is un-loadable mid-cutover, so we
call the route function directly).
"""

import uuid

import pytest
import pytest_asyncio
from error_contract_helpers import handled_app_error_payload
from pydantic import ValidationError
from sqlalchemy import select
from starlette.requests import Request

from app.joysafeter_api.api.v1.credential_groups import create_credential_group
from app.joysafeter_api.api.v1.quickstart import (
    QuickstartAvailableSkill,
    QuickstartChatRequest,
    QuickstartMessage,
    quickstart_chat,
)
from app.joysafeter_application.credentials.application_service import (
    CredentialGroupService,
    CredentialService,
)
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.quickstart import QuickstartDesignService
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredentialGroup
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CreateCredentialGroupInitialMemberRequest,
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import CredentialId, OrganizationId, ProjectId, UserId

TEST_USER_ID = UserId.new()
TEST_ORGANIZATION_ID = OrganizationId.new()
DESIGN_SERVICE = QuickstartDesignService()


async def _make_project(db_session) -> ProjectId:
    org = Organization(id=TEST_ORGANIZATION_ID, name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(id=ProjectId.new(), org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> ProjectId:
    return await _make_project(db_session)


def _auth_ctx(project_id: ProjectId) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id=TEST_USER_ID,
        org_id=TEST_ORGANIZATION_ID,
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/credential-groups",
            "headers": [(b"user-agent", b"quickstart-test/1.0")],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "scheme": "http",
            "query_string": b"",
        }
    )


def _chat_req(*, model_credential_id: CredentialId, engine_kind: str = "codex") -> QuickstartChatRequest:
    return QuickstartChatRequest(
        model_credential_id=model_credential_id,
        engine_kind=engine_kind,
        messages=[QuickstartMessage(role="user", content="help me configure an agent")],
    )


async def _make_model_credential(db_session, project_id: ProjectId, data: dict[str, str]) -> CredentialId:
    cred = await CredentialService(db_session, audit_actor=CredentialAuditActor.system("test")).create(
        CreateCredentialRequest(
            kind="model",
            name=f"m-{uuid.uuid4()}",
            provider="openai",
            protocol="openai_responses",
            data=data,
        ),
        project_id=project_id,
    )
    return cred.id


def test_quickstart_schema_uses_model_credential_id_not_secret_ref():
    fields = QuickstartChatRequest.model_fields
    assert "model_credential_id" in fields
    assert "phase" in fields
    assert "current_step" not in fields
    assert "secret_ref" not in fields


def test_quickstart_schema_accepts_claude_code_engine():
    credential_id = CredentialId.new()
    req = QuickstartChatRequest(
        model_credential_id=credential_id,
        engine_kind="claude_code",
        messages=[QuickstartMessage(role="user", content="build a coding agent")],
    )
    assert req.engine_kind == "claude_code"


def test_quickstart_message_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        QuickstartMessage.model_validate({"role": "user", "content": "build an agent", "unexpected": True})


def test_quickstart_request_accepts_bounded_available_skill_catalog():
    credential_id = CredentialId.new()
    req = QuickstartChatRequest(
        model_credential_id=credential_id,
        engine_kind="codex",
        messages=[QuickstartMessage(role="user", content="build a reviewer")],
        available_skills=[
            QuickstartAvailableSkill(
                id="skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111",
                name="secure-review",
                display_title="Secure Review",
                description="Review code safely",
                latest_version="1.2.0",
            )
        ],
    )

    assert req.available_skills[0].name == "secure-review"


def test_agent_generation_tool_requires_professional_blueprint_contract():
    tool = DESIGN_SERVICE.build_tools()[0]
    schema = tool["input_schema"]
    blueprint = schema["properties"]["blueprint"]

    assert "blueprint" in schema["required"]
    assert set(blueprint["required"]) == {
        "mission",
        "responsibilities",
        "workflow",
        "boundaries",
        "capability_plan",
        "tool_plan",
        "escalation_conditions",
        "output_contract",
        "success_criteria",
        "acceptance_test",
    }
    assert set(blueprint["properties"]["acceptance_test"]["required"]) == {"message", "checks"}
    assert "capability_plan" in blueprint["required"]
    assert "skills" in schema["properties"]
    assert "mcp_servers" in schema["properties"]


def test_agent_generation_tool_reuses_canonical_mcp_server_contract():
    schema = DESIGN_SERVICE.build_tools()[0]["input_schema"]

    streamable_http = schema["$defs"]["StreamableHttpMcpServerConfig"]
    sse = schema["$defs"]["SseMcpServerConfig"]
    local = schema["$defs"]["LocalMcpServerConfig"]
    assert streamable_http["properties"]["type"]["const"] == "streamable_http"
    assert streamable_http["properties"]["auth_requirement"]["default"] == "required"
    assert sse["properties"]["type"]["const"] == "sse"
    assert sse["properties"]["auth_requirement"]["const"] == "none"
    assert local["properties"]["type"]["const"] == "local_stdio"


def test_agent_generation_prompt_limits_skill_ids_to_available_catalog():
    prompt = DESIGN_SERVICE.build_system_prompt(
        available_skills=[
            QuickstartAvailableSkill(
                id="skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111",
                name="secure-review",
                display_title="Secure Review",
                description="Review code safely",
                latest_version="1.2.0",
            ).model_dump()
        ],
    )

    assert "skill_018f6f42-0a51-7cc4-98c8-4f6f0ca5f111" in prompt
    assert "Only attach Skill IDs from this catalog" in prompt


def test_agent_generation_prompt_requires_professional_review_and_focused_clarification():
    prompt = DESIGN_SERVICE.build_system_prompt()

    assert "ask ONE focused clarifying question" in prompt
    assert "professional Agent Blueprint" in prompt
    assert "acceptance test" in prompt
    assert "escalation conditions" in prompt


def test_quickstart_design_stream_owns_only_agent_blueprint_generation():
    prompt = DESIGN_SERVICE.build_system_prompt()
    tools = DESIGN_SERVICE.build_tools()
    assert "Current phase: Design" in prompt
    assert "generate_environment_config" not in prompt
    assert "generate_mcp_credential_group_config" not in prompt
    assert [tool["name"] for tool in tools] == ["generate_agent_config"]


@pytest.mark.asyncio
async def test_credential_group_create_accepts_initial_mcp_members(db_session, project_id):
    response = await create_credential_group(
        CreateCredentialGroupRequest(
            name=f"quickstart-tools-{uuid.uuid4()}",
            initial_members=[
                CreateCredentialGroupInitialMemberRequest(
                    name="github-mcp",
                    mcp_server_url="https://api.github.com/mcp",
                    data={"token_value": "ghp_secret"},
                )
            ],
        ),
        request=_request(),
        db=db_session,
        auth_ctx=_auth_ctx(project_id),
    )

    members = await CredentialGroupService(db_session, audit_actor=CredentialAuditActor.system("test")).list_members(
        response.id,
        project_id=project_id,
        include_archived=True,
    )

    assert response.name.startswith("quickstart-tools-")
    assert len(members) == 1
    assert members[0].name == "github-mcp"
    assert members[0].mcp_server_url == "https://api.github.com/mcp"


@pytest.mark.asyncio
async def test_credential_group_create_initial_member_failure_rolls_back_group(db_session, project_id):
    group_name = f"quickstart-tools-{uuid.uuid4()}"

    with pytest.raises(AppError) as exc:
        await create_credential_group(
            CreateCredentialGroupRequest(
                name=group_name,
                initial_members=[
                    CreateCredentialGroupInitialMemberRequest(
                        name="github-mcp",
                        mcp_server_url="https://api.github.com/mcp",
                        data={"token_value": ""},
                    )
                ],
            ),
            request=_request(),
            db=db_session,
            auth_ctx=_auth_ctx(project_id),
        )

    rows = (
        (
            await db_session.execute(
                select(JoySafeterCredentialGroup).where(
                    JoySafeterCredentialGroup.project_id == project_id,
                    JoySafeterCredentialGroup.name == group_name,
                )
            )
        )
        .scalars()
        .all()
    )
    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"
    assert rows == []


@pytest.mark.asyncio
async def test_quickstart_chat_missing_credential_returns_structured_error(db_session, project_id):
    missing_id = CredentialId.new()

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(model_credential_id=missing_id), _request(), db_session, _auth_ctx(project_id))

    assert await handled_app_error_payload(exc_info.value, status_code=404) == {
        "code": "CREDENTIAL_NOT_FOUND",
        "message": "Credential not found",
        "data": {"credential_id": str(missing_id), "engine_kind": "codex"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.parametrize("data", [{}, {"UNRELATED_SECRET": "must-not-leak"}])
@pytest.mark.asyncio
async def test_quickstart_chat_missing_provider_key_returns_structured_error(
    db_session,
    project_id,
    data,
):
    cred_id = await _make_model_credential(db_session, project_id, data)

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(model_credential_id=cred_id), _request(), db_session, _auth_ctx(project_id))

    payload = await handled_app_error_payload(exc_info.value, status_code=400)
    assert payload == {
        "code": "LLM_SECRET_CREDENTIALS_INCOMPLETE",
        "message": "Required LLM credential fields are missing",
        "data": {
            "provider": "openai",
            "protocol": "openai_responses",
            "required_fields": ["OPENAI_API_KEY"],
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
    assert "must-not-leak" not in str(payload)


@pytest.mark.asyncio
async def test_quickstart_chat_invalid_base_url_returns_structured_error(db_session, project_id):
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "http://169.254.169.254/latest"},
    )

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(model_credential_id=cred_id), _request(), db_session, _auth_ctx(project_id))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_BASE_URL_INVALID",
        "message": "Invalid OPENAI_BASE_URL",
        "data": {
            "provider": "openai",
            "key": "OPENAI_BASE_URL",
            "base_url": "http://169.254.169.254/latest",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_rejects_unallowlisted_openai_base_url(db_session, project_id, monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "api.openai.com")
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "https://evil.example.com/v1"},
    )

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(model_credential_id=cred_id), _request(), db_session, _auth_ctx(project_id))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_BASE_URL_NOT_ALLOWED",
        "message": "OPENAI_BASE_URL host is not allowlisted.",
        "data": {
            "provider": "openai",
            "key": "OPENAI_BASE_URL",
            "base_url": "https://evil.example.com/v1",
            "host": "evil.example.com",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_quickstart_chat_requires_model_when_credential_has_none(db_session, project_id, monkeypatch):
    monkeypatch.setenv("JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS", "api.openai.com")
    # Valid credential (API key + allowlisted base URL) but NO OPENAI_MODEL — the
    # catalog marks the model field optional, so this used to silently fall back to
    # a hardcoded stale model. It must now fail explicitly instead.
    cred_id = await _make_model_credential(
        db_session,
        project_id,
        {"OPENAI_API_KEY": "value", "OPENAI_BASE_URL": "https://api.openai.com/v1"},
    )

    with pytest.raises(AppError) as exc_info:
        await quickstart_chat(_chat_req(model_credential_id=cred_id), _request(), db_session, _auth_ctx(project_id))

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "QUICKSTART_MODEL_REQUIRED",
        "message": "OPENAI_MODEL is required for this provider",
        "data": {
            "provider": "openai",
            "protocol": "openai_responses",
            "key": "OPENAI_MODEL",
        },
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }
