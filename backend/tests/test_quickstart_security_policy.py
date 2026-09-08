import pytest

from app.joysafeter_domain.quickstart.security_policy import recommend_security

pytestmark = pytest.mark.no_db


def test_extracts_explicit_hosts_and_flags_reason():
    rec = recommend_security(["fetch data from https://data.acme.io/report"], None)
    assert "data.acme.io" in rec.recommended_hosts
    assert rec.host_reason == "explicitHosts"


def test_infers_known_service_hosts_from_intent():
    rec = recommend_security(["review my github pull requests"], None)
    assert set(rec.recommended_hosts) >= {"github.com", "api.github.com"}
    assert rec.host_reason == "knownServices"


def test_blocklist_and_local_hosts_are_dropped():
    rec = recommend_security(["ping example.com and service.local and localhost"], None)
    assert rec.recommended_hosts == ()
    assert rec.host_reason == "none"


def test_mcp_servers_in_agent_config_recommend_external_tools():
    rec = recommend_security(
        [],
        {
            "mcp_servers": [
                {
                    "type": "streamable_http",
                    "name": "x",
                    "url": "https://mcp.acme.io/mcp",
                    "auth_requirement": "optional",
                }
            ]
        },
    )
    assert rec.external_tools_recommended is True
    assert rec.external_tools_reason == "mcpServers"
    assert [(server.name, server.url, server.auth_requirement) for server in rec.recommended_mcp_servers] == [
        ("x", "https://mcp.acme.io/mcp", "optional")
    ]


def test_local_stdio_mcp_does_not_recommend_a_credential_group() -> None:
    rec = recommend_security(
        [],
        {
            "mcp_servers": [
                {
                    "type": "local_stdio",
                    "name": "local",
                    "command": "node",
                }
            ]
        },
    )

    assert rec.external_tools_recommended is False
    assert rec.external_tools_reason == "none"
    assert rec.recommended_mcp_servers == ()


def test_no_auth_remote_mcp_does_not_recommend_a_credential_group() -> None:
    rec = recommend_security(
        [],
        {
            "mcp_servers": [
                {
                    "type": "sse",
                    "name": "public",
                    "url": "https://public.example.org/sse",
                    "auth_requirement": "none",
                }
            ]
        },
    )

    assert rec.external_tools_recommended is False
    assert rec.external_tools_reason == "none"
    assert rec.recommended_mcp_servers == ()
    assert rec.recommended_hosts == ("public.example.org",)


def test_structured_mcp_hosts_preserve_exact_internal_and_www_hostnames() -> None:
    rec = recommend_security(
        [],
        {
            "mcp_servers": [
                {
                    "type": "streamable_http",
                    "name": "internal",
                    "url": "http://localhost:8080/mcp",
                    "auth_requirement": "optional",
                },
                {
                    "type": "sse",
                    "name": "web",
                    "url": "https://www.example.com/events",
                    "auth_requirement": "none",
                },
            ]
        },
    )

    assert rec.recommended_hosts == ("localhost", "www.example.com")
    assert rec.host_reason == "explicitHosts"


def test_projects_every_canonical_remote_mcp_server() -> None:
    servers = [
        {
            "type": "streamable_http",
            "name": f"server-{index}",
            "url": f"https://mcp-{index}.example.com/api",
            "auth_requirement": "required",
        }
        for index in range(10)
    ]

    rec = recommend_security([], {"mcp_servers": servers})

    assert [server.name for server in rec.recommended_mcp_servers] == [
        "server-0",
        "server-1",
        "server-2",
        "server-3",
        "server-4",
        "server-5",
        "server-6",
        "server-7",
        "server-8",
        "server-9",
    ]
    assert rec.recommended_hosts == tuple(f"mcp-{index}.example.com" for index in range(10))


def test_final_agent_config_is_authoritative_over_stale_intent():
    rec = recommend_security(
        ["Use GitHub and https://stale.example.net for the old design"],
        {
            "description": "Read Notion pages only",
            "mcp_servers": [],
        },
    )

    assert "github.com" not in rec.recommended_hosts
    assert "api.github.com" not in rec.recommended_hosts
    assert "stale.example.net" not in rec.recommended_hosts
    assert "api.notion.com" in rec.recommended_hosts


def test_credential_intent_recommends_external_tools_without_mcp_servers():
    rec = recommend_security(["I need an external tool credential group"], None)
    assert rec.external_tools_recommended is True
    assert rec.external_tools_reason == "credentialIntent"


def test_hosts_capped_at_eight():
    text = " ".join(f"https://h{i}.example-site.com" for i in range(12))
    rec = recommend_security([text], None)
    assert len(rec.recommended_hosts) <= 8
