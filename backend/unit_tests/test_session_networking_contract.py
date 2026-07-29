from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.joysafeter_api.api.v1.sessions import _networking_with_agent_mcp_hosts  # noqa: E402


def test_limited_session_networking_adds_agent_mcp_hosts_without_mutating_environment_config() -> None:
    networking = {"type": "limited", "allowed_hosts": ["api.example.com"]}
    mcp_configs = [
        {"name": "docs", "url": "https://docs.example.com/mcp"},
        {"name": "api", "url": "https://api.example.com/mcp"},
    ]

    result = _networking_with_agent_mcp_hosts(networking, mcp_configs)

    assert result == {
        "type": "limited",
        "allowed_hosts": ["api.example.com", "docs.example.com"],
    }
    assert networking == {"type": "limited", "allowed_hosts": ["api.example.com"]}


def test_unrestricted_session_networking_does_not_add_agent_mcp_hosts() -> None:
    networking = {"type": "unrestricted", "allowed_hosts": []}

    result = _networking_with_agent_mcp_hosts(
        networking,
        [{"name": "docs", "url": "https://docs.example.com/mcp"}],
    )

    assert result is networking
    assert result == {"type": "unrestricted", "allowed_hosts": []}
