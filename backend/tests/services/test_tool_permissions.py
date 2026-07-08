"""Unit tests for tool permission rule extraction (harness_input_builder).

Covers the mapping from agent toolset configs (the create-agent "工具配置"
checkboxes) into Claude Code settings.json allow/ask permission lists, matching
the official Anthropic Managed Agents permission model (always_allow /
always_ask only).
"""

from types import SimpleNamespace

from app.joysafeter_orchestrator.kernel.harness_input_builder import (
    _build_permission_rules,
    build_permissions_dict,
)


def _agent(tools):
    return SimpleNamespace(tools=tools)


def test_agent_toolset_default_allow():
    agent = _agent([
        {
            "type": "agent_toolset_20260401",
            "configs": [
                {"name": "Bash"},
                {"name": "Read"},
            ],
        }
    ])
    allow, ask = _build_permission_rules(agent)
    # agent toolset default is always_allow
    assert "Bash" in allow and "Read" in allow
    assert ask == []


def test_always_ask_goes_to_ask():
    agent = _agent([
        {
            "type": "agent_toolset_20260401",
            "default_config": {"permission_policy": {"type": "always_allow"}},
            "configs": [
                {"name": "Bash",
                 "permission_policy": {"type": "always_ask"}},
                {"name": "Read"},
            ],
        }
    ])
    allow, ask = _build_permission_rules(agent)
    assert "Bash" in ask
    assert "Read" in allow
    assert "Bash" not in allow


def test_default_config_always_ask_applies_to_configs():
    agent = _agent([
        {
            "type": "agent_toolset_20260401",
            "default_config": {"permission_policy": {"type": "always_ask"}},
            "configs": [
                {"name": "Bash"},
            ],
        }
    ])
    allow, ask = _build_permission_rules(agent)
    assert "Bash" in ask


def test_mcp_toolset_defaults_to_ask():
    # Official model: MCP toolset default is always_ask.
    agent = _agent([
        {
            "type": "mcp_toolset",
            "name": "github",
            "configs": [],
        }
    ])
    allow, ask = _build_permission_rules(agent)
    assert "mcp__github__*" in ask
    assert allow == []


def test_mcp_toolset_always_allow_override():
    agent = _agent([
        {
            "type": "mcp_toolset",
            "name": "github",
            "default_config": {"permission_policy": {"type": "always_allow"}},
            "configs": [],
        }
    ])
    allow, ask = _build_permission_rules(agent)
    assert "mcp__github__*" in allow
    assert ask == []


def test_mcp_toolset_per_tool_policy():
    agent = _agent([
        {
            "type": "mcp_toolset",
            "name": "github",
            "default_config": {"permission_policy": {"type": "always_allow"}},
            "configs": [
                {"name": "create_issue",
                 "permission_policy": {"type": "always_ask"}},
                {"name": "list_issues"},
            ],
        }
    ])
    allow, ask = _build_permission_rules(agent)
    assert "mcp__github__create_issue" in ask
    assert "mcp__github__list_issues" in allow


def test_build_permissions_dict_omits_empty():
    assert build_permissions_dict([], []) == {}
    assert build_permissions_dict(["Bash"], ["WebFetch"]) == {
        "allow": ["Bash"],
        "ask": ["WebFetch"],
    }
