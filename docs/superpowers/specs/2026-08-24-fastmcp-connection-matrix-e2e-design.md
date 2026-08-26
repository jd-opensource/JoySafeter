# fastmcp Connection-Matrix E2E Suite — Design

Date: 2026-08-24
Status: Implemented

## Goal

Build, with `fastmcp`, a matrix of local MCP servers covering the Cartesian
product of transport, authentication, protocol, and host-address form, and
exercise the **live** JoySafeter deployment (`http://localhost:3000/`, admin
`admin@joysafeter.com`) against every cell — from deterministic contract
validation up to a real agent-session end-to-end connection.

## The matrix

```
transport ∈ {sse, streamable_http}
auth      ∈ {none, required}          # required rotates all 3 schemes
protocol  ∈ {http, https}
host      ∈ {domain, ip}
```

= 16 logical cells, realized as **8 fastmcp server processes**
(transport × auth × protocol), each bound to `0.0.0.0` and addressed two ways:

- **domain** → `host.docker.internal`
- **ip** → the host's Docker-reachable LAN IP (auto-detected; default `10.2.67.39`)

Each server exposes deterministic tools (`ping() -> "pong"`, `echo(text) -> text`)
so success/failure is checkable.

### Auth-scheme rotation

The `required` cells rotate through **all three** JoySafeter MCP auth schemes,
matching `validate_mcp_credential_material`:

- `static_bearer`  → `Authorization: Bearer <token>`
- `header_api_key` → `X-Api-Key: <token>` (default header name)
- `custom_header`  → `<Header-Name>: <value_prefix><token>` (e.g. `X-Service-Authorization: Token <token>`)

## Discovered platform facts (grounding)

- Canonical remote MCP config: `{type: streamable_http|sse, name, url, auth_requirement: required|optional|none}`.
  Both SSE and streamable-HTTP are supported by the orchestrator runtime plan,
  the sandbox runner, and `joysafeter-ctl`.
- Auth material is an MCP credential (`kind=mcp`, `mcp_server_url` + `auth_scheme`)
  born into a **credential group**. Secrets are injected as HTTP headers **at the
  Envoy egress gateway**, matched by `(group_id, normalized_mcp_server_url)`.
- There is **no lightweight MCP connectivity probe**. The only way JoySafeter
  actually connects to an MCP server is by **running an agent session in a
  sandbox**, whose harness reaches the server through Envoy egress.
- Flow: credential group (MCP member) → agent (`mcp_servers` + `mcp_toolset`
  tool + `model_credential_id`) → session (`credential_group_ids`).
- Running deployment flags: `JOYSAFETER_SSRF_HTTPS_ONLY=false`,
  `JOYSAFETER_SSRF_BLOCK_PRIVATE=false`, `JOYSAFETER_MCP_REQUIRE_HTTPS=false`
  ⇒ all 16 transport/protocol/host cells are accepted when declared anonymous
  (plain HTTP and private addresses are allowed). Managed credential injection
  remains restricted to `streamable_http`; SSE declarations with `required` or
  `optional` authentication fail at the Agent boundary. Always-true invariants
  remain: metadata-IP SSRF block, malformed-URL rejection, and cross-group
  normalized-URL conflict.
- Login: `POST /api/v1/auth/sign-in/email` (cookie JWT) or `/auth/login/form`
  (token). CSRF applies to cookie-authenticated mutations.
- Sandboxes/Envoy reach host-run servers via `host.docker.internal`
  (docker `host-gateway`).
- Available deps in `backend/.venv`: `fastmcp 2.14.1`, `pytest 9.0.2`,
  `pytest_asyncio 1.3.0`, `cryptography 44.0.3`, `uvicorn 0.40.0`,
  `starlette 0.50.0`, `httpx 0.28.1`. `trustme` absent ⇒ generate CA with
  `cryptography`.

## Location & stack

New **`tests/mcp_connection_matrix/`** suite, self-contained, Python + `pytest`. Uses `fastmcp`
for servers/clients, `httpx` for the JoySafeter API client, `uvicorn` for TLS
serving, `cryptography` for the CA. Runs against the live stack; excluded from
backend unit runs.

## Layers

### L0 — Server matrix fixture
Launch the 8 fastmcp servers in spawned processes via `uvicorn.Server`.
- Unless `JOYSAFETER_TEST_BASE_PORT` is explicit, select the first available
  contiguous 8-port block at or after 3400.
- Every process exposes a private random readiness token. The parent accepts a
  listener only when the token matches, preventing stale or foreign services
  from being mistaken for the current matrix.
- HTTPS servers use a generated CA + leaf cert (SAN covers `host.docker.internal`,
  `localhost`, `127.0.0.1`, host LAN IP, `192.168.5.2`).
- Auth servers enforce the expected **static** header via a Starlette ASGI
  middleware wrapping `FastMCP.http_app(transport=...)` (fastmcp's built-in auth
  is OAuth/JWT-oriented; static-token validation is a small custom shim).
- Anonymous servers enforce nothing.

### L1 — Direct self-test (no JoySafeter)
A `fastmcp.Client` connects to each of the 16 URLs directly and asserts:
- no-auth accepts anonymous; the tool call returns the expected value;
- auth rejects missing/wrong credential (401) and accepts the correct one;
- HTTPS validates against the generated CA.
This proves the matrix independent of JoySafeter and gives clean per-cell diagnostics.

### L2 — Deterministic contract layer (real admin API, always runs)
Login as admin → register every transport/protocol/host cell, create credential
groups for all authentication schemes, and create sessions for supported
combinations. Assert:
- anonymous SSE and all streamable-HTTP modes follow the current Agent contract;
- SSE `required`/`optional` declarations fail at the Agent configuration boundary;
- URL normalization + `(group_id, url)` matching under current flags;
- always-true invariants (metadata-IP SSRF block, malformed-URL → conflict,
  cross-group URL conflict).
No LLM tokens. All resources namespaced with a unique run prefix and cleaned up
(archive/delete) at the end.

### L3 — Gated live session (real end-to-end)
For feasible cells, run a **real agent session** and assert via session events
that the MCP tool was discovered/called through Envoy egress with credential
injection. Gated behind an env flag **and** the presence of a usable model
credential in the admin project, so the deterministic layers never depend on
LLM availability/cost.

## Known risks (resolve during implementation)
1. **Envoy upstream TLS trust** for HTTPS live cells. If the orchestrator's
   egress cannot trust the generated CA, HTTPS is proven at L1 (direct) + L2
   (contract) and L3-HTTPS is documented as limited.
2. **Host "ip" reachability** from sandbox containers on macOS (host-gateway vs
   LAN IP). L2 does not require reachability; L3 does.
3. **Static-auth shim** exact shape in fastmcp 2.14 (Starlette middleware over
   `http_app`).

## Deliverables (`tests/mcp_connection_matrix/`)
- `matrix.py` — cell definitions.
- `tls.py` — CA + leaf cert generation.
- `mcp_servers.py` — fastmcp server builders + auth shim + uvicorn launcher/fixtures.
- `joysafeter_client.py` — API client (login, create group/cred/agent/session,
  events, cleanup).
- `test_l1_direct.py`, `test_l2_contract.py`, `test_l3_live.py`.
- `conftest.py`, `README.md` (deterministic default; `--live` opt-in).

## Out of scope
- Changing product behavior. This is a test/e2e deliverable only.
- `local_stdio` transport (matrix is remote-transport only).
