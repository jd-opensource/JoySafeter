# MCP Egress Endpoint Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve configured MCP HTTP request targets exactly through limited-networking Envoy routes, disable unsafe transport retries, and fail closed for unsupported limited-networking SSE.

**Architecture:** Keep the orchestrator-owned runtime plan and Envoy xDS boundary. Separate slash-insensitive credential lookup from exact routing identity, compile Streamable HTTP servers into exact opaque-path rewrites, and express path/retry behavior with enums shared by JSON and protobuf renderers. Prove the behavior first at the runtime-plan and renderer boundaries, then with a runtime-plan-driven live Envoy test.

**Tech Stack:** Rust 2021, `url`, Envoy v3 JSON/protobuf xDS, Tokio, Docker-based integration tests, Python 3, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-mcp-egress-endpoint-routing-design.md`

## Global Constraints

- Keep the current orchestrator + Envoy architecture; do not introduce an MCP gateway.
- Preserve existing credential database normalization and uniqueness behavior; no schema migration.
- Preserve configured path, trailing slash, query order, and duplicate query parameters for routing identity.
- Limited-networking Streamable HTTP uses one exact opaque route and one exact upstream rewrite.
- MCP egress routes disable automatic Envoy retries.
- Limited-networking SSE fails closed; unrestricted SSE remains supported.
- Redirects remain fail closed and must not broaden the real-host allowlist.
- Preserve unrelated working-tree changes, including the existing `ProjectId` edits in `mcp_runtime_plan.rs`.
- Do not commit changes unless the user explicitly requests it.

---

### Task 1: Exact MCP Endpoint Identity

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_url.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_runtime_plan.rs`

**Interfaces:**
- Consumes: existing `mcp_url::normalize(raw: &str) -> String` as the credential compatibility key.
- Produces: `mcp_url::routing_identity(raw: &str) -> Option<String>`; `McpEndpoint { configured_url, credential_match_key, routing_identity, host, port, path, query, tls, vetted_addresses }`.
- Produces: `McpRuntimePlanError::LimitedNetworkingSseUnsupported { server_name: String }`.

- [ ] **Step 1: Add failing URL identity tests**

Add Rust tests proving that routing identity lowercases scheme/host and removes default ports while preserving `/mcp` versus `/mcp/`, raw query order, and duplicate query parameters:

```rust
#[test]
fn routing_identity_preserves_request_target_identity() {
    assert_eq!(
        routing_identity(" HTTPS://Example.COM:443/mcp?b=2&a=1&a=3 ").as_deref(),
        Some("https://example.com/mcp?b=2&a=1&a=3")
    );
    assert_ne!(
        routing_identity("https://example.com/mcp"),
        routing_identity("https://example.com/mcp/")
    );
}
```

- [ ] **Step 2: Add failing runtime-plan tests**

Add tests in `mcp_runtime_plan.rs` asserting:

```rust
assert_eq!(endpoint.path, "/mcp");
assert_eq!(endpoint.credential_match_key, "http://host.docker.internal:3404/mcp");
assert_eq!(endpoint.routing_identity, "http://host.docker.internal:3404/mcp");
assert!(runner[0].url.ends_with('/'));
assert_ne!(plan_without_slash.egress_revision, plan_with_slash.egress_revision);
```

Add a limited-networking SSE test expecting:

```rust
Err(McpRuntimePlanError::LimitedNetworkingSseUnsupported {
    server_name: "events".to_string(),
})
```

and an unrestricted SSE test proving the configured URL remains unchanged.

- [ ] **Step 3: Run focused tests and confirm failure**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline mcp_url -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline mcp_runtime_plan -- --test-threads=1
```

Expected: new routing identity and limited-SSE assertions fail because the implementation still normalizes the routing path and accepts limited SSE.

- [ ] **Step 4: Implement exact endpoint parsing**

Implement `routing_identity` by trimming, parsing with `url::Url`, rejecting missing hosts, credentials, fragments, and non-HTTP(S) schemes, removing only default ports, and serializing without modifying `path` or `query`.

Change `McpEndpoint` to:

```rust
pub struct McpEndpoint {
    pub configured_url: String,
    pub credential_match_key: String,
    pub routing_identity: String,
    pub host: String,
    pub port: u16,
    pub path: String,
    pub query: Option<String>,
    pub tls: bool,
    pub vetted_addresses: Vec<IpAddr>,
}
```

Make `remote_endpoint` preserve `parsed.path()` exactly, representing an empty HTTP path as `/`. Use `credential_match_key` only for credential lookup and duplicate errors. Use `routing_identity` in `route_identity` and `egress_revision`. Reject `McpTransport::Sse` only when `network_mode == EffectiveNetworkMode::Limited`.

- [ ] **Step 5: Run focused tests and confirm pass**

Run the two focused Cargo commands from Step 3. Expected: all `mcp_url` and `mcp_runtime_plan` tests pass.

---

### Task 2: Typed Egress Path and Retry Contracts

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_runtime_plan.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/mcp_live_envoy.rs`

**Interfaces:**
- Produces: `EgressPathMatcher::{Any, Exact(String), Prefix(String)}`.
- Produces: `EgressPathMapping::{Passthrough { matcher }, RewriteExact { exposed_path, upstream_path }, RewritePrefix { exposed_prefix, upstream_prefix }}`.
- Produces: `EgressRetryMode::{Disabled, SafeIdempotent}`.
- Changes: `EgressCredentialRoute` replaces `match_prefix`, `exact_path`, and `upstream_prefix` with `path_mapping` and adds `retry_mode`.

- [ ] **Step 1: Add failing model-construction tests**

Update test helpers to construct explicit mappings, then add assertions that MCP routes are represented as:

```rust
EgressPathMapping::RewriteExact {
    exposed_path: format!("/r/{route_key}/"),
    upstream_path: "/mcp".to_string(),
}
```

with `EgressRetryMode::Disabled`, while LLM/Git/external-service routes retain `SafeIdempotent` and their existing passthrough/prefix behavior.

- [ ] **Step 2: Run compile-focused tests and confirm failure**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline lds_backend --no-run
```

Expected: compile errors identify every constructor and renderer still using the removed booleans/string fields.

- [ ] **Step 3: Introduce enums and migrate constructors**

Define the three enums beside `EgressCredentialRoute`, derive `Debug`, `Clone`, `PartialEq`, and `Eq`, and change the route struct to:

```rust
pub struct EgressCredentialRoute {
    pub id: String,
    pub kind: EgressKind,
    pub exposure: EgressExposure,
    pub match_host: String,
    pub path_mapping: EgressPathMapping,
    pub retry_mode: EgressRetryMode,
    pub upstream_host: String,
    pub upstream_port: u16,
    pub upstream_tls: bool,
    pub cluster_name: String,
    pub vetted_addresses: Vec<String>,
    pub inject_headers: Vec<(String, String)>,
    pub remove_headers: Vec<String>,
}
```

Map existing constructors as follows:

- transparent exact allowlists → `Passthrough { matcher: Exact(path) }`
- transparent prefix allowlists → `Passthrough { matcher: Prefix(prefix) }`
- placeholder LLM/Git routes → `RewritePrefix`
- placeholder MCP Streamable HTTP routes → `RewriteExact`
- existing non-MCP routes → `SafeIdempotent`
- MCP routes → `Disabled`

- [ ] **Step 4: Run compile-focused tests and confirm pass**

Run the Step 2 command. Expected: the crate and test targets compile with no references to `match_prefix`, `exact_path`, or `upstream_prefix` on `EgressCredentialRoute`.

---

### Task 3: JSON and Protobuf Renderer Parity

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`

**Interfaces:**
- Consumes: `EgressPathMapping` and `EgressRetryMode` from Task 2.
- Produces: identical route match/rewrite/retry semantics from `build_virtual_hosts_json` and `build_virtual_hosts_proto`.

- [ ] **Step 1: Add failing renderer tests**

Add table-driven JSON/protobuf parity tests for:

```rust
Passthrough { matcher: Any }
Passthrough { matcher: Exact("/health".into()) }
Passthrough { matcher: Prefix("/api/".into()) }
RewriteExact { exposed_path: "/r/key/".into(), upstream_path: "/mcp".into() }
RewritePrefix { exposed_prefix: "/r/key/".into(), upstream_prefix: "/base/".into() }
```

For `RewriteExact`, require Envoy `path` plus `prefix_rewrite`; on an exact match this replaces the complete path and is supported by the pinned protobuf API. For `Disabled`, require no `retry_policy`; for `SafeIdempotent`, require the existing `5xx,reset,connect-failure` policy with two retries.

- [ ] **Step 2: Run renderer tests and confirm failure**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline sandbox::lds_backend::tests -- --test-threads=1
```

Expected: exact rewrite and retry-mode assertions fail against the old renderer logic.

- [ ] **Step 3: Implement shared mapping helpers**

Add small renderer-local helpers that project the typed mapping into JSON and protobuf match/action fields. Ensure:

- `Passthrough` emits no rewrite.
- `RewriteExact` emits exact match + exact path rewrite.
- `RewritePrefix` emits prefix match + prefix rewrite.
- placeholder exposure controls host rewrite only, not path semantics.
- `Disabled` emits no retry policy.
- `SafeIdempotent` preserves the existing policy.

- [ ] **Step 4: Run renderer tests and confirm pass**

Run the Step 2 command. Expected: all LDS JSON/protobuf tests pass.

---

### Task 4: Compile Streamable HTTP Exact Routes

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_runtime_plan.rs`

**Interfaces:**
- Consumes: exact `McpEndpoint.path`, `EgressPathMapping::RewriteExact`, and `EgressRetryMode::Disabled`.
- Produces: runner URL `http://mcp-egress.internal/r/<route-key>/[?<configured-query>]` and exact route `/r/<route-key>/ -> <configured-path>`.

- [ ] **Step 1: Add failing route-projection tests**

Add assertions for configured `http://host.docker.internal:3404/mcp?b=2&a=1&a=3`:

```rust
assert_eq!(runner.url, format!("http://{MCP_EGRESS_HOST}/r/{route_key}/?b=2&a=1&a=3"));
assert_eq!(
    route.path_mapping,
    EgressPathMapping::RewriteExact {
        exposed_path: format!("/r/{route_key}/"),
        upstream_path: "/mcp".to_string(),
    }
);
assert_eq!(route.retry_mode, EgressRetryMode::Disabled);
```

Also assert there is exactly one MCP route and no descendant prefix mapping.

- [ ] **Step 2: Run focused runtime-plan test and confirm failure**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline mcp_runtime_plan -- --test-threads=1
```

Expected: route mapping still uses the prior prefix semantics until implementation is updated.

- [ ] **Step 3: Implement exact Streamable HTTP compilation**

In `ResolvedMcpRuntimePlan::egress_routes`, emit only Streamable HTTP limited-network routes and set:

```rust
path_mapping: EgressPathMapping::RewriteExact {
    exposed_path: format!("/r/{}/", server.route_key),
    upstream_path: endpoint.path.clone(),
},
retry_mode: EgressRetryMode::Disabled,
```

Keep the configured query only on the runner URL; Envoy forwards it unchanged without merging or sorting.

- [ ] **Step 4: Run focused runtime-plan test and confirm pass**

Run the Step 2 command. Expected: all runtime-plan tests pass.

---

### Task 5: Runtime-Plan-Driven Live Envoy Regression

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/mcp_live_envoy.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/tests/fixtures/mcp_live_fixture.py`

**Interfaces:**
- Consumes: `resolve_mcp_runtime_plan`, `apply_mcp_network_policy`, `ResolvedMcpRuntimePlan::runner_servers`, and `ResolvedMcpRuntimePlan::egress_routes`.
- Produces: a live regression proving configured `/mcp` reaches upstream as `/mcp`, not `/mcp/`, and POST is not retried.

- [ ] **Step 1: Extend the fixture with deterministic MCP probes**

Add fixture behavior:

- `POST /mcp` returns JSON including the exact method/path/query and increments a process-local request counter.
- `POST /mcp/` returns `307 Location: http://host.docker.internal:3404/mcp` to reproduce the original failure.
- `POST /retry-probe` returns `503` and reports the request count so duplicate attempts are observable.

- [ ] **Step 2: Replace hand-built MCP policy with a runtime plan**

Build the live route from:

```rust
let raw = serde_json::json!([{
    "type": "streamable_http",
    "name": "matrix",
    "url": format!("http://mcp-http.fixture:{port}/mcp?tenant=a&tenant=b"),
    "auth_requirement": "none"
}]);
let mut plan = resolve_mcp_runtime_plan(...)?;
apply_mcp_network_policy(&mut plan, &StaticResolver::new(fixture_ip), &McpNetworkPolicy::default()).await?;
```

Feed `plan.egress_routes()` into `SandboxCredentials` and issue requests to `plan.runner_servers()[0].url` through the sandbox Unix socket.

- [ ] **Step 3: Add live assertions**

Assert:

- upstream receives `POST /mcp?tenant=a&tenant=b` exactly;
- response is `200`, not `307` or `403`;
- `/r/<route-key>/child` is denied;
- the retry probe records one upstream attempt for one MCP POST;
- direct real-host access remains denied.

- [ ] **Step 4: Compile the live test**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --test mcp_live_envoy --no-run
```

Expected: compilation succeeds.

- [ ] **Step 5: Run the gated live test when Docker prerequisites exist**

Run:

```bash
JOYSAFETER_RUN_LIVE_ENVOY=1 cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --test mcp_live_envoy -- --ignored --nocapture --test-threads=1
```

Expected: pass. If the required fixture image or Docker capability is unavailable, record the exact prerequisite failure without weakening deterministic tests.

---

### Task 6: L3 Failure Semantics and Documentation

**Files:**
- Modify: `tests/mcp_connection_matrix/test_l3_live.py`
- Modify: `docs/superpowers/specs/2026-08-25-mcp-egress-endpoint-routing-design.md`
- Create: `docs/superpowers/evidence/2026-08-25-mcp-egress-endpoint-routing-verification.md`

**Interfaces:**
- Consumes: live-test gating before task creation.
- Produces: once a live task is created, timeout, terminal failure, and missing MCP evidence are test failures rather than skips.

- [ ] **Step 1: Add a deterministic helper test for terminal enforcement**

Extract a helper such as:

```python
def _require_successful_live_task(final: dict | None, *, context: str) -> dict:
    assert final is not None, f"{context}: task did not reach a terminal state"
    assert final.get("status") not in _FAILED_STATUSES, (
        f"{context}: status={final.get('status')} error={final.get('error')!r}"
    )
    return final
```

Add focused tests proving `None` and failed statuses raise `AssertionError`, while `completed` passes.

- [ ] **Step 2: Run focused pytest and confirm failure**

Run from `tests/mcp_connection_matrix/`:

```bash
../../backend/.venv/bin/python -m pytest test_l3_live.py -q --collect-only
```

Expected before implementation: collection reflects no helper regression tests or the new tests fail when invoked directly.

- [ ] **Step 3: Replace post-start skips with assertions**

Keep skips only for preconditions (`--live` disabled or no usable model credential). After `create_task` succeeds, call `_require_successful_live_task` and use direct assertions for tool evidence in both no-auth and credentialed cases. Update docstrings to state that execution failures are failures.

- [ ] **Step 4: Update design status and write verification evidence**

Record the implemented invariant, files changed, targeted commands, live-test result or prerequisite limitation, and remaining redirect/SSE product constraints in the evidence document. Mark the design implementation status without changing its approved decisions.

- [ ] **Step 5: Run focused pytest collection/tests**

Run from `tests/mcp_connection_matrix/`:

```bash
../../backend/.venv/bin/python -m pytest test_l3_live.py -q --collect-only
```

Expected: successful collection with live tests still gated by `--live`.

---

### Task 7: Targeted and Broad Verification

**Files:**
- Verify only; no planned production edits.

**Interfaces:**
- Consumes: all prior tasks.
- Produces: current evidence that endpoint preservation, typed routing, renderer parity, and test semantics are sound.

- [ ] **Step 1: Format and inspect the patch**

Run:

```bash
cargo fmt --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --check
git diff --check
git diff -- backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_url.rs backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_runtime_plan.rs backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs backend/app/joysafeter_orchestrator_rs/tests/mcp_live_envoy.rs backend/app/joysafeter_orchestrator_rs/tests/fixtures/mcp_live_fixture.py tests/mcp_connection_matrix/test_l3_live.py docs/superpowers/specs/2026-08-25-mcp-egress-endpoint-routing-design.md docs/superpowers/evidence/2026-08-25-mcp-egress-endpoint-routing-verification.md
```

Expected: formatting and whitespace checks pass; diff contains no unrelated reversions.

- [ ] **Step 2: Run targeted Rust tests**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline mcp_url -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline mcp_runtime_plan -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline sandbox::lds_backend::tests -- --test-threads=1
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline --test mcp_live_envoy --no-run
```

Expected: all selected tests pass or compile.

- [ ] **Step 3: Run the broader orchestrator suite**

Run:

```bash
cargo test --manifest-path backend/app/joysafeter_orchestrator_rs/Cargo.toml --offline -- --test-threads=1
```

Expected: all non-ignored orchestrator tests pass. Report unrelated pre-existing failures separately without changing scope.

- [ ] **Step 4: Run Python verification**

Run:

```bash
cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l1_direct.py test_l2_contract.py -q
cd tests/mcp_connection_matrix && ../../backend/.venv/bin/python -m pytest test_l3_live.py -q --collect-only
```

Expected: deterministic matrix layers pass and L3 collects successfully.

- [ ] **Step 5: Record final verification evidence**

Update `docs/superpowers/evidence/2026-08-25-mcp-egress-endpoint-routing-verification.md` with exact command outputs, skipped live prerequisites, and deployment implications. Do not claim the gated live test passed unless it was actually run successfully.
