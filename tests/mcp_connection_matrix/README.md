# fastmcp Connection-Matrix E2E Suite

End-to-end tests that build a matrix of local MCP servers with **fastmcp** and
exercise the **live** JoySafeter deployment against every combination of
transport, authentication, protocol, and host-address form.

## The matrix

```
transport ∈ {sse, streamable_http}
auth      ∈ {none, required}          # required rotates all 3 auth schemes
protocol  ∈ {http, https}
host      ∈ {domain, ip}
```

= 16 logical cells, realized as **8 fastmcp server processes**
(transport × protocol × auth), each addressed two ways:
`domain` → `host.docker.internal`, `ip` → the host's LAN IP.

The `required` servers rotate through all three JoySafeter MCP auth schemes:
`static_bearer` (`Authorization: Bearer …`), `header_api_key` (`X-Api-Key: …`),
and `custom_header` (`X-Service-Authorization: Token …`).

## Layers

| File | Layer | Needs | LLM tokens |
|------|-------|-------|-----------|
| `test_l1_direct.py` | **L1** direct fastmcp client → every server | matrix servers | no |
| `test_l2_contract.py` | **L2** real admin API registration + binding contract | live API | no |
| `test_l3_live.py` | **L3** real agent session runs a task, calls an MCP tool | live API + `--live` + model credential | yes |

- **L1** proves each server: no-auth accepts anonymous; auth rejects missing/wrong
  credentials and accepts the correct one; https validates against a generated CA;
  the `ping`/`echo` tools return expected values.
- **L2** drives the real admin API (bearer auth) to register every transport and
  host form, binds supported sessions, and asserts JoySafeter's contract:
  streamable HTTP supports managed credentials while SSE is anonymous-only;
  URL normalization, metadata-IP blocking, malformed-URL rejection, missing
  required credentials, relevant cross-group ambiguity, and unrelated duplicate
  tolerance remain enforced. Deterministic; every
  created resource is cleaned up (agents force-deleted, which cascades sessions;
  groups deleted).
- **L3** is the real "实战" run: it configures an agent with a real model
  credential + engine, submits a task, and asserts from the session event stream
  that the agent connected to a matrix MCP server and invoked a tool. Gated and
  best-effort — it **skips** (never false-passes) when the run cannot converge.

## Running

All commands use the backend venv interpreter.

```bash
cd tests/mcp_connection_matrix

# L1 — offline server matrix self-test (fast, no deployment needed)
../../backend/.venv/bin/python -m pytest test_l1_direct.py -v

# L2 — deterministic contract layer against the live stack
../../backend/.venv/bin/python -m pytest test_l2_contract.py -v

# L1 + L2 (default deterministic suite)
../../backend/.venv/bin/python -m pytest test_l1_direct.py test_l2_contract.py

# L3 — gated real end-to-end run (real sandbox + LLM tokens)
../../backend/.venv/bin/python -m pytest test_l3_live.py -v --live
```

### Options / environment

| Option | Env var | Default |
|--------|---------|---------|
| `--jsf-base-url` | `JOYSAFETER_TEST_BASE_URL` | `http://localhost:8000` |
| `--jsf-email` | `JOYSAFETER_TEST_EMAIL` | `admin@joysafeter.com` |
| `--jsf-password` | `JOYSAFETER_TEST_PASSWORD` | required for L2/L3 |
| `--live` | — | off |
| — | `JOYSAFETER_TEST_HOST_IP` | auto-detected LAN IP |
| — | `JOYSAFETER_TEST_BASE_PORT` | first free 8-port block at/after `3400` |

> The web UI at `:3000` is a SPA that calls the API at `:8000`
> (`NEXT_PUBLIC_API_URL`), so the suite talks to `:8000` directly. Auth uses a
> bearer token (`/auth/login/form`), which the API treats as header auth and
> therefore exempts from CSRF.

## Files

- `matrix.py` — cell/server definitions and per-run auth tokens (singletons).
- `tls.py` — CA + leaf cert generation (`cryptography`; SAN covers all host forms).
- `mcp_servers.py` — fastmcp server builders, static-auth ASGI shim, spawned-process launcher.
- `mcp_client.py` — fastmcp client helpers (host-reachable URL, CA-trusting TLS factory).
- `joysafeter_client.py` — JoySafeter REST client (login, create, run, cleanup).
- `conftest.py` — fixtures (`matrix_servers`, `jsf`, `tracker`, `ca_path`).

## Notes on design choices

- **Servers run in spawned processes**, not threads: fastmcp's HTTP lifespan opens
  an in-memory task-queue lock bound to a single event loop, which breaks when
  several servers share one interpreter. Separate processes also avoid touching
  the deployment's Redis.
- **Ports are isolated per run** unless `JOYSAFETER_TEST_BASE_PORT` is explicitly
  set. Readiness uses a per-process instance token, so a stale listener can never
  be mistaken for the server started by the current test run.
- **HTTPS on the wire** is proven at L1 (direct, against the generated CA). L3
  uses `http` to sidestep the open question of Envoy trusting the test CA for
  upstream TLS (see the design doc's known risks).
- **L1 host addressing:** `host.docker.internal` is a container-only name and does
  not resolve on the host where L1 runs, so L1's `domain` form maps to loopback
  and its `ip` form uses the LAN IP. The domain/ip distinction against JoySafeter
  is exercised in L2/L3.

Design doc: `docs/superpowers/specs/2026-08-24-fastmcp-connection-matrix-e2e-design.md`.
