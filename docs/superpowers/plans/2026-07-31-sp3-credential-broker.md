# SP-3: Reference-Based Credentials + CredentialBroker (Zero Standing Secret) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.
> **Controller note:** implementer subagents in this workspace frequently cannot run `cargo`/`git` (Bash safety-classifier outage). The controller must build/test/commit every task itself before trusting it; never commit a subagent's code on its word. Preserve exact predicates in behavior-preserving refactors.

**Goal:** Remove standing decrypted secrets from both egress data planes. Policies carry `credential_ref` (non-secret) instead of plaintext `inject_headers`; a `CredentialBroker` in the orchestrator resolves ref→secret on demand; the K8s gateway and Docker Envoy each resolve **per request** by calling the orchestrator's `CredentialResolutionService`.

**Architecture (decisions locked with the user):**
- The **orchestrator** owns the `CredentialBroker` (it has Vault/DB); it is the single decrypt point.
- Both data planes resolve **per request**: the K8s `joysafeter-egress-gateway` (a separate, dependency-light binary with **no** DB/Vault) calls the orchestrator's resolution endpoint; Docker's Envoy calls the **same** endpoint via an **ext_authz** filter. The spec's "gateway resolves in-process" is impossible (lib-crate boundary) and is superseded by this.
- The control plane pushes **refs only** (`SandboxEgressPolicy` becomes safe to persist/log).
- `EgressEnforcer::isolation()` etc. from SP-2 are unaffected; this builds on SP-1/SP-2.

**Tech Stack:** Rust, axum (gateway + resolution HTTP), tonic/`ext_authz` proto (Envoy callout), reqwest, sqlx, `VaultCipher`. Crate dir: `backend/app/joysafeter_orchestrator_rs`.

## Global Constraints

- **Lib-crate boundary is inviolable.** `egress::policy` + `egress::gateway` must remain compilable without DB/Vault/kernel (the `joysafeter-egress-gateway` binary depends only on them). The `CredentialBroker` and `CredentialResolutionService` live OUTSIDE that subgraph (in `kernel`/orchestrator-only modules). `EgressCredentialRoute` must carry only a **non-secret** `CredentialRef` — no `VaultCipher`, no secret strings.
- **Zero standing secret:** after this, no `SandboxEgressPolicy`, gateway store, Envoy LDS config, DB row, or log line contains a decrypted provider/MCP/Git/external secret. Secrets exist only transiently in the broker at resolution time (short-TTL memory cache, evicted on teardown).
- **Behavior-preserving at the boundary:** for a given sandbox+route, the header injected upstream (name + value) must be byte-identical to today's; sandbox-supplied auth stripping unchanged.
- No new standing infra beyond the resolution endpoint (reuse the existing orchestrator gRPC/HTTP server where possible). Structured error `CREDENTIAL_RESOLVE_FAILED` on resolution failure.
- Conventional commits; `cargo fmt`; warning-clean.

## The `CredentialRef` model (Task 1 — the load-bearing design)

Today's four secret sources and their DB lookups (from the current builders):
- **LLM** (`egress/llm.rs`): secret is the model API key, currently **decrypted into `env`** by `harness_input_builder` before the resolver runs, then moved into `inject_headers`. This is the thorny one — see Task 1.
- **MCP** (`egress/credential.rs::build_mcp_egress`): `joysafeter_vault_credentials.token_value` matched by `mcp_server_url`, keyed by session `vault_ids`.
- **Git** (`build_git_egress`): `joysafeter_session_repos.encrypted_token` by `session_id` + `mount_name`.
- **External** (`build_external_egress`): `joysafeter_secrets.data[key]` by `name` + `project_id`, with an `inject` spec (bearer/api_key/cookie).

`CredentialRef` (in `egress::policy`, non-secret, serializable) addresses all four uniformly:

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum CredentialRef {
    /// LLM model key sourced from a managed Secret (see Task 1 for how the LLM
    /// key stops being decrypted into env).
    Llm { secret_name: String, secret_key: String, project_id: Option<String> },
    /// MCP server token from a session vault credential, matched by URL.
    Mcp { vault_id: Uuid, mcp_server_url: String },
    /// Git token from a session repo.
    Git { session_id: Uuid, mount_name: String },
    /// External-service secret field.
    External { secret_name: String, secret_key: String, project_id: Option<String> },
}
```

`EgressCredentialRoute` changes: **remove** `pub inject_headers: Vec<(String, String)>`; **add**:
```rust
pub credential_ref: CredentialRef,
pub inject_header: String,     // e.g. "authorization", "x-api-key", "cookie"
pub inject_scheme: InjectScheme, // Bearer | Basic | Raw
```
`InjectScheme` tells the broker how to format the resolved secret into the header value (mirrors today's `format!("Bearer {token}")` / `Basic {b64}` / raw). `remove_headers` (sandbox-auth stripping) stays.

**Task 1 LLM design (DECIDED — clean-slate, pre-launch, no legacy path).** The system is not yet live, so we do NOT preserve the plaintext-LLM-key-in-`env` path or byte-identical-with-literals behavior. LLM becomes a **first-class credential** exactly like MCP/Git/External:

- **The LLM credential value never enters `env`.** Today `SandboxResolver::merge_secret_ref_into_env` (`kernel/sandbox_resolver.rs:902`) decrypts every key of a Secret's `data` into `env`, and `extract_llm_egress` (`egress/llm.rs:22`) later reads that decrypted value. In the new design, the merge becomes **provenance-aware**: for each Secret key it would inject, if that key name is an LLM-credential key (per `llm_provider_registry` detection keys — matched on **key NAME only, never decrypting the value**), it records the identity `(secret_name, key, project_id)` instead of decrypting the value into `env`, and inserts only the provider placeholder. All non-credential keys decrypt into `env` as before.
- **`extract_llm_egress` emits a ref, not a value.** It keeps its base-URL / host-allowlist / SSRF logic (base URL is not a secret and stays in `env`), but sources the credential **identity** from the provenance map and emits `CredentialRef::Llm { secret_name, secret_key, project_id }`. The route carries `inject_header` = the registry's `header_name` and `inject_scheme` = `Bearer` (when `spec.is_bearer`) or `Raw`.
- **LLM credentials MUST be Secret-backed.** If a provider detection key appears only as a plaintext literal (from `agent.env` / `environment.config.env_vars`, no Secret provenance), that is a misconfiguration: **fail closed** — do not inject, emit a clear `warn!` and no LLM route (sandbox reaches no LLM upstream). No inline plaintext path exists.
- **Interface (Produces, for later tasks):** `merge_secret_ref_into_env` gains an out-param mapping credential-key → `(secret_name, project_id)`; `resolve_agent_env_from` threads it and hands it to `extract_llm_egress(env, &provenance, allowed_hosts)`. The provenance map holds **no secret values** — only Secret names + key names.

This makes the "provenance loss" that made LLM thorny structurally impossible: the credential keeps its identity from Secret → ref → broker, and is decrypted only transiently in the broker. Confirmed feasible: `agent.secret_ref` + `agent.project_id` are available in `resolve_agent_env_from`, and the registry already enumerates the credential key names.

## Components

1. **`CredentialBroker`** (`src/kernel/credential_broker.rs`, orchestrator-only): `async fn resolve(&self, cred_ref: &CredentialRef, scope: &SandboxScope) -> anyhow::Result<SecretMaterial>`. Backed by the existing DB queries + `VaultCipher`; short-TTL in-memory cache keyed by `(sandbox_id, route_id)`; `evict(sandbox_id)` on teardown. Returns the *formatted header value* (applies `InjectScheme`).
2. **`CredentialResolutionService`** (orchestrator gRPC/HTTP): (a) an Envoy-compatible **ext_authz** gRPC server, and (b) a plain `POST /resolve` HTTP endpoint for the K8s gateway. Both authenticate the caller (sandbox token / mTLS / service token), map `(sandbox_id, route_id)` → `CredentialRef` via the installed policy, call the broker, and return the header to inject. Never logs secret values.
3. **K8s gateway** (`egress/gateway.rs`): replace the in-store plaintext injection (`gateway.rs:596-606`) with a call to `CredentialResolutionService` (`/resolve`) using the route's `credential_ref`/scheme carried in the pushed policy. Gateway still holds refs (non-secret) in its store.
4. **Docker Envoy** (`sandbox/lds_backend.rs`): replace baked `inject_headers` (`lds_backend.rs:459,1262`) with an `ext_authz` filter pointing at the orchestrator; Envoy injects the header from the ext_authz OK response.

## Data flow (target)

K8s: sandbox → gateway (authz route) → `POST orchestrator/resolve {sandbox_id, route_id}` → broker resolves ref → returns `{header, value}` → gateway injects, strips sandbox auth, forwards.
Docker: sandbox → Envoy (route match) → ext_authz → orchestrator resolution service → OK + `headers_to_add` → Envoy injects → forwards.

## Task decomposition (each its own spec→impl→review; both providers green after each)

- **Task 1 — `CredentialRef` + policy schema + builders.** Add `CredentialRef`/`InjectScheme` to `egress/policy.rs`; change `EgressCredentialRoute` (drop `inject_headers`, add ref/header/scheme). Rewrite the four builders (`egress/llm.rs`, `egress/credential.rs`) to emit refs instead of decrypting. For LLM, implement the DECIDED clean-slate design above: make `kernel/sandbox_resolver.rs`'s env merge provenance-aware (LLM credential key → ref, never decrypted into env; Secret-backed only, else fail closed). Update `lds_backend.rs`/`gateway.rs`/tests to the new fields at the type level (data planes still functionally inject in later tasks — here just make it compile + carry refs). Behavior temporarily broken for real injection is acceptable *only within this task*; end state of the task keeps tests compiling with refs.
  - Risk: this is a schema change touching every builder + the resolver env merge + both data planes + many tests. Largest task.
- **Task 2 — `CredentialBroker`.** New `src/kernel/credential_broker.rs`: `resolve` for all four ref kinds (move the decrypt logic out of the builders into here), cache + eviction, `SecretMaterial`/`InjectScheme` formatting. Unit-tested against the DB (guarded like existing `test_pool` tests) + a pure formatting test.
- **Task 3 — `CredentialResolutionService` (orchestrator).** HTTP `POST /resolve` + auth; map `(sandbox_id, route_id)`→ref via a policy registry (the enforcer already installs per-sandbox policy — extend it to keep refs queryable orchestrator-side); call broker; structured errors. Tests: authorized resolve returns the formatted header; missing policy/route → deny; unknown sandbox → deny.
- **Task 4 — K8s gateway resolves per request.** Replace `gateway.rs` in-store injection with a `/resolve` call (the gateway gets the resolution endpoint URL + a service token via config/policy). Gateway store now holds refs only. Tests: proxy forwards with the injected header obtained from a stubbed resolution endpoint; no secret in the gateway store.
- **Task 5 — Docker Envoy ext_authz.** Add the ext_authz gRPC server to the resolution service; rework `lds_backend.rs` LDS to reference the ext_authz filter instead of baked headers; the Envoy config carries no secret. Tests: generated LDS contains the ext_authz cluster/filter and no injected secret values; an integration-style test of the ext_authz handler returning `headers_to_add`.
- **Task 6 — Teardown/recovery/observability.** `evict` on sandbox teardown; restart recovery rebuilds refs (already ref-only, so recovery no longer decrypts); add `CREDENTIAL_RESOLVE_FAILED` to the structured error set; metrics/audit without secret values.

Order 1→2→3→4→5→6. Tasks 4 and 5 can be reviewed independently once 3 lands.

## Verification (end-to-end, per the workspace's "real chain, not forged" bar)

- **Static:** grep the whole tree — no `inject_headers` plaintext on `EgressCredentialRoute`; `egress::policy`/`egress::gateway` still compile in the lib crate (`cargo build --bin joysafeter-egress-gateway`); `VaultCipher` not referenced from `egress::policy`.
- **Unit/integration:** `cargo test` green; broker resolve/evict tests; resolution-service authz tests; gateway proxy-with-resolution test; Envoy LDS-has-ext_authz-no-secret test.
- **Live zero-standing-secret proof (Colima k3s, per project_colima_k3s_sandbox.md recipe):** exec into a sandbox pod → confirm it holds only a placeholder key; `kubectl get pod -o yaml` + the gateway's installed policy contain **no** real secret; a runtime-random model challenge succeeds through the gateway; the orchestrator resolution-service log shows a resolve for that `sandbox_id`+`route_id` at the matching timestamp; cross-correlate. Negative control: direct upstream from the pod is blocked.

## Open items to resolve during tasks
- ~~Task 1: LLM-secret-identity recovery~~ **DECIDED** (see "Task 1 LLM design" above): clean-slate provenance-aware env merge; LLM must be Secret-backed; literal LLM keys fail closed. Task 1 now legitimately edits `kernel/sandbox_resolver.rs`.
- Task 3/5: caller authentication mechanism for the resolution service (sandbox token vs mTLS vs service-account) and the exact ext_authz proto version/shape.
- Task 2: cache TTL + eviction policy (bound staleness vs rotation latency).
