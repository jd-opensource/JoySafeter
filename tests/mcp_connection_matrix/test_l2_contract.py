"""L2 — deterministic contract layer against the live JoySafeter deployment.

Drives the real admin API (bearer auth) to register every matrix cell and bind
sessions, asserting JoySafeter's MCP configuration contract. No LLM tokens and no
sandbox runs, so this layer is deterministic and always safe to run.

Two valid runtime patterns:
  * no-auth server  -> declared on the agent's ``mcp_servers`` (auth_requirement
    "none"); no credential group.
  * credentialed server -> declared on the agent's ``mcp_servers`` and registered
    as a credential-group MEMBER with the same normalized URL; the group is
    authorized by the session.

Under the running deployment flags (SSRF_HTTPS_ONLY=false, BLOCK_PRIVATE=false,
MCP_REQUIRE_HTTPS=false) all 16 cells are accepted; the always-true invariants
(metadata-IP block, malformed-URL reject, missing required credentials, and
relevant cross-group ambiguity) are asserted separately.

Run:  cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l2_contract.py -v
"""

from __future__ import annotations

import secrets

import pytest

import matrix

CELLS = matrix.CELLS
NOAUTH_CELLS = [c for c in CELLS if not c.requires_auth]
AUTH_CELLS = [c for c in CELLS if c.requires_auth]
AUTH_INJECTION_CELLS = [c for c in AUTH_CELLS if c.transport == "streamable_http"]
SSE_CELLS = [c for c in CELLS if c.transport == "sse"]

_RUN = secrets.token_hex(3)


def _name(cell_id: str, kind: str) -> str:
    return f"jsfmcp-{_RUN}-{kind}-{cell_id}"


def _server_entry(cell, *, name: str, auth_requirement: str) -> dict:
    return {
        "type": cell.transport,
        "name": name,
        "url": cell.url,
        "auth_requirement": auth_requirement,
    }


# --- registration: agent-declared MCP servers (all 16 cells) ---------------------


@pytest.mark.parametrize("cell", CELLS, ids=[c.id for c in CELLS])
def test_agent_mcp_server_registration(jsf, tracker, cell):
    """JoySafeter accepts every transport/protocol/host form as an agent server
    and persists the URL in canonical (already-normalized) form."""
    res = jsf.create_agent(
        name=_name(cell.id, "agent"),
        mcp_servers=[_server_entry(cell, name="srv", auth_requirement="none")],
        tools=[{"type": "mcp_toolset", "mcp_server_name": "srv"}],
    ).require(context=f"create agent for {cell.id}")
    tracker.agent_ids.append(res.data["id"])

    servers = res.data.get("mcp_servers") or []
    assert len(servers) == 1, f"{cell.id}: expected 1 mcp_server, got {servers}"
    entry = servers[0]
    assert entry["type"] == cell.transport, f"{cell.id}: transport {entry['type']}"
    assert entry["url"] == cell.url, (
        f"{cell.id}: url persisted as {entry['url']!r}, expected {cell.url!r}"
    )
    assert entry["auth_requirement"] == "none"


# --- registration: credential-group members (8 auth cells, all 3 schemes) --------


@pytest.mark.parametrize("cell", AUTH_CELLS, ids=[c.id for c in AUTH_CELLS])
def test_group_member_registration(jsf, tracker, cell):
    """Each auth scheme (bearer / api_key / custom_header) registers as a group
    member with the URL and scheme persisted."""
    res = jsf.create_group(
        _name(cell.id, "grp"),
        initial_members=[
            {
                "name": _name(cell.id, "mem"),
                "mcp_server_url": cell.url,
                "data": cell.auth.credential_data(),
                "auth_scheme": cell.auth.scheme,
            }
        ],
    ).require(context=f"create group for {cell.id}")
    gid = res.data["id"]
    tracker.group_ids.append(gid)

    members = jsf.list_members(gid)
    assert len(members) == 1, f"{cell.id}: expected 1 member, got {members}"
    member = members[0]
    assert member["mcp_server_url"] == cell.url, (
        f"{cell.id}: member url {member['mcp_server_url']!r}"
    )
    assert member["auth_scheme"] == cell.auth.scheme, (
        f"{cell.id}: scheme {member['auth_scheme']!r}"
    )


# --- session binding: no-auth declared server (8 no-auth cells) ------------------


@pytest.mark.parametrize("cell", NOAUTH_CELLS, ids=[c.id for c in NOAUTH_CELLS])
def test_session_binds_noauth_declared_server(jsf, tracker, cell):
    agent = jsf.create_agent(
        name=_name(cell.id, "na-agent"),
        mcp_servers=[_server_entry(cell, name="srv", auth_requirement="none")],
        tools=[{"type": "mcp_toolset", "mcp_server_name": "srv"}],
    ).require(context=f"agent {cell.id}")
    tracker.agent_ids.append(agent.data["id"])

    session = jsf.create_session(
        agent_id=agent.data["id"], title=_name(cell.id, "na-sess")
    ).require(context=f"session {cell.id}")
    tracker.session_ids.append(session.data["id"])
    assert session.data.get("status") in {
        "idle",
        "pending",
        "queued",
        "created",
        "running",
    }


# --- session binding: credentialed group member (4 streamable HTTP cells) --------


@pytest.mark.parametrize(
    "cell", AUTH_INJECTION_CELLS, ids=[c.id for c in AUTH_INJECTION_CELLS]
)
def test_session_binds_credentialed_group(jsf, tracker, cell):
    group = jsf.create_group(
        _name(cell.id, "cg-grp"),
        initial_members=[
            {
                "name": _name(cell.id, "cg-mem"),
                "mcp_server_url": cell.url,
                "data": cell.auth.credential_data(),
                "auth_scheme": cell.auth.scheme,
            }
        ],
    ).require(context=f"group {cell.id}")
    tracker.group_ids.append(group.data["id"])

    agent = jsf.create_agent(
        name=_name(cell.id, "cg-agent"),
        mcp_servers=[_server_entry(cell, name="srv", auth_requirement="required")],
        tools=[{"type": "mcp_toolset", "mcp_server_name": "srv"}],
    ).require(context=f"agent {cell.id}")
    tracker.agent_ids.append(agent.data["id"])

    session = jsf.create_session(
        agent_id=agent.data["id"],
        credential_group_ids=[group.data["id"]],
        title=_name(cell.id, "cg-sess"),
    ).require(context=f"session {cell.id}")
    tracker.session_ids.append(session.data["id"])


# --- invariants (negative) -------------------------------------------------------


def test_malformed_url_rejected(jsf, tracker):
    res = jsf.create_group(
        _name("inv", "badurl"),
        initial_members=[
            {
                "name": _name("inv", "bm"),
                "mcp_server_url": "not-a-url",
                "data": {"token_value": "x"},
                "auth_scheme": "static_bearer",
            }
        ],
    )
    if res.ok:  # should not happen; register for cleanup then fail
        tracker.group_ids.append(res.data["id"])
    assert res.status == 422, f"expected 422, got {res.status} ({res.error_code})"


def test_metadata_ip_rejected(jsf, tracker):
    res = jsf.create_group(
        _name("inv", "meta"),
        initial_members=[
            {
                "name": _name("inv", "mm"),
                "mcp_server_url": "http://169.254.169.254/mcp",
                "data": {"token_value": "x"},
                "auth_scheme": "static_bearer",
            }
        ],
    )
    if res.ok:
        tracker.group_ids.append(res.data["id"])
    assert res.status == 422, f"expected 422, got {res.status} ({res.error_code})"


@pytest.mark.parametrize("cell", SSE_CELLS, ids=[c.id for c in SSE_CELLS])
@pytest.mark.parametrize("auth_requirement", ["required", "optional"])
def test_sse_managed_auth_rejected(jsf, tracker, cell, auth_requirement):
    res = jsf.create_agent(
        name=_name(cell.id, f"sse-{auth_requirement}"),
        mcp_servers=[
            _server_entry(
                cell,
                name="srv",
                auth_requirement=auth_requirement,
            )
        ],
    )
    if res.ok:
        tracker.agent_ids.append(res.data["id"])
    assert res.status == 400
    assert res.error_code == "AGENT_MCP_AUTH_REQUIREMENT_UNSUPPORTED"


def test_declared_and_member_same_url_is_the_credentialed_success_path(jsf, tracker):
    cell = AUTH_INJECTION_CELLS[0]
    group = jsf.create_group(
        _name("inv", "dm-grp"),
        initial_members=[
            {
                "name": _name("inv", "dm-mem"),
                "mcp_server_url": cell.url,
                "data": cell.auth.credential_data(),
                "auth_scheme": cell.auth.scheme,
            }
        ],
    ).require(context="declared+member group")
    tracker.group_ids.append(group.data["id"])

    agent = jsf.create_agent(
        name=_name("inv", "dm-agent"),
        mcp_servers=[_server_entry(cell, name="srv", auth_requirement="required")],
        tools=[{"type": "mcp_toolset", "mcp_server_name": "srv"}],
    ).require(context="declared+member agent")
    tracker.agent_ids.append(agent.data["id"])

    session = jsf.create_session(
        agent_id=agent.data["id"], credential_group_ids=[group.data["id"]]
    ).require(context="declared+member session")
    tracker.session_ids.append(session.data["id"])


def test_cross_group_same_url_conflict(jsf, tracker):
    cell = AUTH_INJECTION_CELLS[0]

    def members(tag):
        return [
            {
                "name": _name("inv", tag),
                "mcp_server_url": cell.url,
                "data": cell.auth.credential_data(),
                "auth_scheme": cell.auth.scheme,
            }
        ]

    g1 = jsf.create_group(_name("inv", "xg1"), initial_members=members("xg1m")).require(
        context="xg1"
    )
    g2 = jsf.create_group(_name("inv", "xg2"), initial_members=members("xg2m")).require(
        context="xg2"
    )
    tracker.group_ids += [g1.data["id"], g2.data["id"]]

    agent = jsf.create_agent(
        name=_name("inv", "xg-agent"),
        mcp_servers=[_server_entry(cell, name="srv", auth_requirement="optional")],
    ).require(context="xg agent")
    tracker.agent_ids.append(agent.data["id"])

    session = jsf.create_session(
        agent_id=agent.data["id"], credential_group_ids=[g1.data["id"], g2.data["id"]]
    )
    if session.ok:
        tracker.session_ids.append(session.data["id"])
    assert (
        session.status == 409 and session.error_code == "CREDENTIAL_GROUP_URL_CONFLICT"
    ), (
        f"expected 409 CREDENTIAL_GROUP_URL_CONFLICT, got {session.status} {session.error_code}"
    )


def test_url_normalization_equivalence_via_conflict(jsf, tracker):
    """Normalization is observable through matching, not the stored display value:
    JoySafeter persists the raw URL but keys uniqueness on a single normal form
    (lowercased scheme+host, default port removed, trailing slash stripped). Two
    differently-spelled but equivalent URLs must therefore collide when bound
    together."""
    canonical = "https://host.docker.internal/mcp-norm"
    equivalent = "HTTPS://Host.Docker.Internal:443/mcp-norm/"  # same normal form

    g1 = jsf.create_group(
        _name("inv", "n1"),
        initial_members=[
            {
                "name": _name("inv", "n1m"),
                "mcp_server_url": canonical,
                "data": {"token_value": "x"},
                "auth_scheme": "static_bearer",
            }
        ],
    ).require(context="norm g1")
    g2 = jsf.create_group(
        _name("inv", "n2"),
        initial_members=[
            {
                "name": _name("inv", "n2m"),
                "mcp_server_url": equivalent,
                "data": {"token_value": "x"},
                "auth_scheme": "static_bearer",
            }
        ],
    ).require(context="norm g2")
    tracker.group_ids += [g1.data["id"], g2.data["id"]]

    agent = jsf.create_agent(
        name=_name("inv", "n-agent"),
        mcp_servers=[
            {
                "type": "streamable_http",
                "name": "srv",
                "url": canonical,
                "auth_requirement": "optional",
            }
        ],
    ).require(context="norm agent")
    tracker.agent_ids.append(agent.data["id"])

    session = jsf.create_session(
        agent_id=agent.data["id"], credential_group_ids=[g1.data["id"], g2.data["id"]]
    )
    if session.ok:
        tracker.session_ids.append(session.data["id"])
    assert (
        session.status == 409 and session.error_code == "CREDENTIAL_GROUP_URL_CONFLICT"
    ), (
        f"equivalent URLs should normalize to the same key and conflict; "
        f"got {session.status} {session.error_code}"
    )
