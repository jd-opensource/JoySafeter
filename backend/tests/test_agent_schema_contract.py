import pytest
from pydantic import TypeAdapter, ValidationError

from app.joysafeter_api.api.v1.quickstart import QuickstartAgentContext
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterAgentResponse,
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
    McpAuthRequirement,
    McpServerConfig,
    McpTransport,
)
from app.joysafeter_shared.ids import SkillId

pytestmark = pytest.mark.no_db

AGENT_ID = "agent_018f6f42-0a51-7cc4-98c8-4f6f0ca5f001"
MCP_SERVER_CONFIG_ADAPTER = TypeAdapter(McpServerConfig)


def _mcp_server_config(**payload: object):
    return MCP_SERVER_CONFIG_ADAPTER.validate_python(payload)


def test_agent_requests_use_system_field() -> None:
    create = JoySafeterCreateAgentRequest(name="Agent", engine_kind="claude", system="Be precise")
    update = JoySafeterUpdateAgentRequest(system="Be concise")

    assert create.system == "Be precise"
    assert update.system == "Be concise"


def test_agent_create_requires_explicit_engine_kind() -> None:
    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(name="Agent")


def test_agent_tool_policy_serialization_preserves_nullable_inheritance_contract() -> None:
    request = JoySafeterCreateAgentRequest(
        name="Agent",
        engine_kind="claude",
        tools=[
            {
                "type": "agent_toolset_20260401",
                "configs": [{"name": "Bash"}],
            },
            {
                "type": "mcp_toolset",
                "mcp_server_name": "docs",
                "configs": [{"name": "search"}],
            },
        ],
    )

    tools = request.model_dump(mode="json")["tools"]

    assert tools[0]["default_config"] is None
    assert tools[0]["configs"][0]["permission_policy"] is None
    assert tools[1]["default_config"] is None
    assert tools[1]["configs"][0]["permission_policy"] is None


def test_agent_toolset_disabled_default_is_preserved_for_runtime_compilation() -> None:
    request = JoySafeterCreateAgentRequest(
        name="Agent",
        engine_kind="codex",
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {
                    "enabled": False,
                    "permission_policy": {"type": "always_allow"},
                },
            }
        ],
    )

    default_config = request.model_dump(mode="json")["tools"][0]["default_config"]

    assert default_config == {
        "permission_policy": {"type": "always_allow"},
        "enabled": False,
    }


@pytest.mark.parametrize("request_type", [JoySafeterCreateAgentRequest, JoySafeterUpdateAgentRequest])
def test_agent_requests_reject_removed_system_prompt_field(request_type) -> None:
    payload = {"system_prompt": "old field"}
    if request_type is JoySafeterCreateAgentRequest:
        payload["name"] = "Agent"
        payload["engine_kind"] = "claude"

    with pytest.raises(ValidationError):
        request_type(**payload)


def test_agent_skill_refs_reject_packed_archives_and_drafts() -> None:
    skill_id = SkillId.new()

    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(
            name="Agent",
            engine_kind="claude",
            skills=[{"name": "packed", "tar_gz_b64": "eA=="}],
        )

    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(
            name="Agent",
            engine_kind="claude",
            skills=[{"type": "custom", "skill_id": str(skill_id), "version": "draft"}],
        )


def test_agent_requests_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(name="Agent", engine_kind="claude", skill_ids=["skill_123"])


def test_quickstart_context_uses_system_field() -> None:
    context = QuickstartAgentContext(name="Agent", system="Be precise")
    assert context.system == "Be precise"
    assert "secret_ref" not in QuickstartAgentContext.model_fields

    with pytest.raises(ValidationError):
        QuickstartAgentContext(name="Agent", system_prompt="old field")


@pytest.mark.parametrize("transport", [McpTransport.STREAMABLE_HTTP, McpTransport.SSE])
def test_remote_mcp_config_persists_only_canonical_transport_and_required_auth(
    transport: McpTransport,
) -> None:
    config = _mcp_server_config(type=transport, name=" docs ", url=" https://example.com/mcp?tenant=a ")

    assert config.to_persisted() == {
        "type": transport.value,
        "name": "docs",
        "url": "https://example.com/mcp?tenant=a",
        "auth_requirement": McpAuthRequirement.REQUIRED.value,
    }


@pytest.mark.parametrize("transport", ["url", "http", "streamable-http", "stdio"])
def test_mcp_config_rejects_removed_transport_aliases(transport: str) -> None:
    payload = {"type": transport, "name": "legacy", "url": "https://example.com/mcp"}
    if transport == "stdio":
        payload = {"type": transport, "name": "legacy", "command": "node"}

    with pytest.raises(ValidationError):
        MCP_SERVER_CONFIG_ADAPTER.validate_python(payload)


def test_mcp_config_requires_explicit_transport() -> None:
    with pytest.raises(ValidationError):
        _mcp_server_config(name="implicit", url="https://example.com/mcp")


@pytest.mark.parametrize("requirement", ["required", "optional", "none"])
def test_remote_mcp_config_preserves_explicit_auth_requirement(requirement: str) -> None:
    config = _mcp_server_config(
        type="sse",
        name="events",
        url="https://example.com/sse",
        auth_requirement=requirement,
    )

    assert config.to_persisted()["auth_requirement"] == requirement


def test_local_stdio_mcp_config_is_command_only() -> None:
    config = _mcp_server_config(
        type="local_stdio",
        name=" local-tools ",
        command=" node ",
        args=["server.js", "--stdio"],
        env={"MODE": "safe"},
    )

    assert config.to_persisted() == {
        "type": "local_stdio",
        "name": "local-tools",
        "command": "node",
        "args": ["server.js", "--stdio"],
        "env": {"MODE": "safe"},
    }


def test_agent_response_serializes_only_transport_specific_mcp_fields() -> None:
    response = JoySafeterAgentResponse(
        id=AGENT_ID,
        name="Agent",
        engine_kind="claude",
        mcp_servers=[
            {
                "type": "streamable_http",
                "name": "docs",
                "url": "https://example.com/mcp",
                "auth_requirement": "optional",
            },
            {
                "type": "local_stdio",
                "name": "local",
                "command": "node",
            },
        ],
        version=1,
        created_at="2026-08-24T00:00:00Z",
        updated_at="2026-08-24T00:00:00Z",
    )

    assert response.model_dump(mode="json")["mcp_servers"] == [
        {
            "type": "streamable_http",
            "name": "docs",
            "url": "https://example.com/mcp",
            "auth_requirement": "optional",
        },
        {
            "type": "local_stdio",
            "name": "local",
            "command": "node",
            "args": [],
            "env": {},
        },
    ]


def test_agent_response_requires_explicit_remote_mcp_auth_requirement() -> None:
    with pytest.raises(ValidationError):
        JoySafeterAgentResponse(
            id=AGENT_ID,
            name="Agent",
            engine_kind="claude",
            mcp_servers=[
                {
                    "type": "streamable_http",
                    "name": "docs",
                    "url": "https://example.com/mcp",
                }
            ],
            version=1,
            created_at="2026-08-24T00:00:00Z",
            updated_at="2026-08-24T00:00:00Z",
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "streamable_http", "name": "remote"},
        {"type": "streamable_http", "name": "remote", "url": "https://example.com", "command": "node"},
        {"type": "local_stdio", "name": "local"},
        {"type": "local_stdio", "name": "local", "command": "node", "url": "https://example.com"},
        {"type": "local_stdio", "name": "local", "command": "node", "auth_requirement": "required"},
        {"type": "sse", "name": "   ", "url": "https://example.com/sse"},
    ],
)
def test_mcp_config_rejects_cross_transport_fields(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        MCP_SERVER_CONFIG_ADAPTER.validate_python(payload)


@pytest.mark.parametrize(
    "url",
    [
        "http://user:password@example.com/mcp",
        "https://example.com/mcp#fragment",
        "http://169.254.169.254/latest/meta-data",
        "http://[fe80::1]/mcp",
        "http://[ff02::1]/mcp",
    ],
)
def test_remote_mcp_config_rejects_unsafe_literal_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        _mcp_server_config(type="streamable_http", name="unsafe", url=url)
