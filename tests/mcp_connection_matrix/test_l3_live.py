"""L3 — gated live end-to-end run against the real JoySafeter deployment.

This is the "真实端到端实战" layer: it configures a real agent (real model
credential + engine), runs an actual task in a sandbox, and asserts — from the
session event stream — that the agent connected to a matrix MCP server through
the platform and invoked a tool.

Gated: only runs with ``--live`` AND when a usable model credential exists.
It costs real LLM tokens and spins up a sandbox, so it is never part of the
deterministic default run.

Feasibility choices and known risks:
  * uses the ``domain`` host form (``host.docker.internal``), which sandboxes
    reach via docker host-gateway;
  * uses ``http`` to avoid the open question of Envoy trusting the generated CA
    for upstream TLS;
  * the no-auth cell is the primary proof (agent-declared server, direct);
  * the credentialed cell is best-effort (Envoy egress credential injection).

Run:  cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l3_live.py -v --live
"""

from __future__ import annotations

import secrets
import time

import pytest

import matrix

_RUN = secrets.token_hex(3)
_PREFERRED_ENGINES = ("claude", "codex", "native", "pi")

_TERMINAL_STATUSES = {
    "completed",
    "succeeded",
    "failed",
    "error",
    "terminated",
    "cancelled",
    "timeout",
}
_FAILED_STATUSES = {"failed", "error", "terminated", "cancelled", "timeout"}


def _pick_model(jsf):
    creds = jsf.list_model_credentials()
    for engine in _PREFERRED_ENGINES:
        for cred in creds:
            if engine in (cred.get("compatible_engine_ids") or []) and not cred.get(
                "archived_at"
            ):
                return engine, cred["id"], cred.get("name")
    return None


@pytest.fixture(scope="session")
def model_engine(jsf, live_enabled):
    if not live_enabled:
        pytest.skip("live layer disabled (pass --live to enable)")
    picked = _pick_model(jsf)
    if picked is None:
        pytest.skip("no usable model credential available in the admin project")
    return picked


def _poll_task(jsf, task_id: str, timeout: float = 300.0) -> dict | None:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        res = jsf.get_task(task_id)
        if res.ok and isinstance(res.data, dict):
            last = res.data
            if last.get("status") in _TERMINAL_STATUSES:
                return last
        time.sleep(3)
    return last


def _events(jsf, session_id: str) -> list[dict]:
    res = jsf.get_session_events(session_id, limit=500)
    data = res.data
    if isinstance(data, dict):
        return data.get("data") or []
    return data or []


def _mcp_tool_evidence(
    events: list[dict], task: dict | None
) -> tuple[list[dict], bool]:
    """Return (tool_use events, whether the ping marker appears anywhere).

    A ``agent.tool_use`` event is emitted by the harness when it actually invokes
    a tool — strong evidence the MCP server was reached. The ping marker (``pong``)
    corroborates a real round-trip (it is not present in the prompt)."""
    tool_uses = [e for e in events if e.get("event_type") == "agent.tool_use"]
    blob = " ".join(str(e) for e in events)
    if task:
        blob += " " + str(task.get("output") or "")
    return tool_uses, (matrix.PING_RESULT in blob)


def _require_successful_live_task(final: dict | None, *, context: str) -> dict:
    assert final is not None, f"{context}: task did not reach a terminal state"
    assert final.get("status") not in _FAILED_STATUSES, (
        f"{context}: status={final.get('status')} error={final.get('error')!r}"
    )
    return final


@pytest.mark.parametrize("final", [None, {"status": "failed", "error": "boom"}])
def test_require_successful_live_task_rejects_non_success(final):
    with pytest.raises(AssertionError):
        _require_successful_live_task(final, context="probe")


def test_require_successful_live_task_accepts_completed():
    final = {"status": "completed", "output": "pong"}
    assert _require_successful_live_task(final, context="probe") is final


_PROMPT = (
    "You have an MCP tool named `ping` that takes no arguments. "
    "Call the `ping` tool exactly once and then reply with only its exact return value."
)


def test_live_noauth_mcp_tool_call(matrix_servers, jsf, tracker, model_engine):
    """Primary proof: a real agent run connects to a no-auth matrix MCP server
    (declared on the agent) and invokes a tool through the platform."""
    engine, model_id, _ = model_engine
    cell = next(
        c
        for c in matrix.CELLS
        if not c.requires_auth
        and c.transport == "streamable_http"
        and c.server.protocol == "http"
        and c.host_form == "domain"
    )

    agent = jsf.create_agent(
        name=f"jsfmcp-{_RUN}-live-na",
        engine_kind=engine,
        model_credential_id=model_id,
        mcp_servers=[
            {
                "type": cell.transport,
                "name": "matrix",
                "url": cell.url,
                "auth_requirement": "none",
            }
        ],
        tools=[
            {
                "type": "mcp_toolset",
                "mcp_server_name": "matrix",
                "default_config": {"permission_policy": {"type": "always_allow"}},
            }
        ],
        system="You are a connectivity test agent. Use the provided MCP tools when asked.",
    ).require(context="live no-auth agent")
    tracker.agent_ids.append(agent.data["id"])

    session = jsf.create_session(
        agent_id=agent.data["id"], title=f"jsfmcp-{_RUN}-live-na-sess"
    ).require(context="live no-auth session")
    tracker.session_ids.append(session.data["id"])

    task = jsf.create_task(
        agent_id=agent.data["id"],
        prompt=_PROMPT,
        chat_session_id=session.data["id"],
        timeout_sec=300,
    ).require(context="live no-auth task")

    final = _require_successful_live_task(
        _poll_task(jsf, task.data["id"], timeout=300),
        context="no-auth live MCP run",
    )

    events = _events(jsf, session.data["id"])
    tool_uses, saw_pong = _mcp_tool_evidence(events, final)
    assert tool_uses or saw_pong, (
        f"no MCP tool evidence for {cell.id}: status={final.get('status')} "
        f"output={final.get('output')!r} events={[e.get('event_type') for e in events]}"
    )


def test_live_credentialed_mcp_tool_call(matrix_servers, jsf, tracker, model_engine):
    """A credentialed matrix server is reached through Envoy header injection."""
    engine, model_id, _ = model_engine
    cell = next(
        c
        for c in matrix.CELLS
        if c.requires_auth
        and c.transport == "streamable_http"
        and c.server.protocol == "http"
        and c.host_form == "domain"
    )

    group = jsf.create_group(
        f"jsfmcp-{_RUN}-live-cg",
        initial_members=[
            {
                "name": f"jsfmcp-{_RUN}-live-cg-m",
                "mcp_server_url": cell.url,
                "data": cell.auth.credential_data(),
                "auth_scheme": cell.auth.scheme,
            }
        ],
    ).require(context="live cred group")
    tracker.group_ids.append(group.data["id"])

    agent = jsf.create_agent(
        name=f"jsfmcp-{_RUN}-live-ca",
        engine_kind=engine,
        model_credential_id=model_id,
        mcp_servers=[
            {
                "type": cell.transport,
                "name": "matrix",
                "url": cell.url,
                "auth_requirement": "required",
            }
        ],
        tools=[
            {
                "type": "mcp_toolset",
                "mcp_server_name": "matrix",
                "default_config": {"permission_policy": {"type": "always_allow"}},
            }
        ],
        system="You are a connectivity test agent. Use the provided MCP tools when asked.",
    ).require(context="live cred agent")
    tracker.agent_ids.append(agent.data["id"])

    session = jsf.create_session(
        agent_id=agent.data["id"],
        credential_group_ids=[group.data["id"]],
        title=f"jsfmcp-{_RUN}-live-ca-sess",
    ).require(context="live cred session")
    tracker.session_ids.append(session.data["id"])

    task = jsf.create_task(
        agent_id=agent.data["id"],
        prompt=_PROMPT,
        chat_session_id=session.data["id"],
        timeout_sec=300,
    ).require(context="live cred task")

    final = _require_successful_live_task(
        _poll_task(jsf, task.data["id"], timeout=300),
        context="credentialed live MCP run",
    )

    events = _events(jsf, session.data["id"])
    tool_uses, saw_pong = _mcp_tool_evidence(events, final)
    assert tool_uses or saw_pong, (
        f"no MCP tool evidence via egress injection for {cell.id}: "
        f"status={final.get('status')} output={final.get('output')!r} "
        f"events={[e.get('event_type') for e in events]}"
    )
