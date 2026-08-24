# MCP Runtime Plan Hardening Implementation Plan

> **Status (2026-08-24):** Implemented with an irreversible canonical-contract
> cutover. Historical values are handled only by migration
> `20260824_000001_mcp_contract_cutover.py`; API, frontend, CLI, protobuf, runner,
> and orchestrator runtime paths accept canonical values only.

> The unchecked task list below is the original execution plan, not the completion
> ledger. Final implementation and current verification results are recorded in
> `docs/superpowers/evidence/2026-08-24-mcp-runtime-plan-verification.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one fail-closed MCP runtime plan that drives runner configuration, credential injection, network policy, and lifecycle readiness.

**Architecture:** Python validates and persists explicit MCP transport/authentication intent. The Rust orchestrator resolves that durable intent plus bound credentials and effective networking into one immutable `ResolvedMcpRuntimePlan`; runner-safe and Envoy-secret projections are generated only from that plan. PostgreSQL generation state and Envoy xDS ACK jointly gate execution readiness.

**Tech Stack:** Python 3.12+, Pydantic v2, FastAPI, SQLAlchemy, PostgreSQL, TypeScript, React 19, Rust, SQLx, Envoy v1.37.1, pytest, Vitest, Cargo.

**Spec:** `docs/superpowers/specs/2026-08-23-mcp-runtime-plan-architecture.md`

## Global Constraints

- PostgreSQL remains authoritative for durable lifecycle and generation state.
- The orchestrator owns runtime planning, sandbox lifecycle, and Envoy policy publication.
- Remote secrets never enter runner input, sandbox files, logs, or fingerprints.
- Missing required credentials, unsupported transports, unsafe destinations, and unacknowledged policies fail closed.
- Historical transport/authentication values are rewritten once by migration; runtime paths contain no legacy fallback.
- Real MCP upstream hosts are not added to the ordinary allowlist.
- Every production change starts with a failing test.
- Do not modify `.deps/SkillSpector`.
- Do not commit unless the user explicitly requests it.

---

### Task 1: Python MCP Credential Contract

**Files:**
- Modify: `backend/app/joysafeter_domain/credentials/types.py`
- Create: `backend/app/joysafeter_domain/credentials/mcp_auth.py`
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_credential.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`
- Modify: `backend/app/joysafeter_api/api/v1/credential_groups.py`
- Modify: `backend/contracts/credential_domain_contract.json`
- Test: `backend/tests/test_credential_schema.py`
- Test: `backend/tests/test_credential_service.py`
- Test: `backend/tests/test_credential_domain_contract.py`
- Test: `backend/tests/test_credentials_api.py`

**Interfaces:**
- Produces: `CredentialAuthScheme.STATIC_BEARER`, `HEADER_API_KEY`, and `CUSTOM_HEADER`.
- Produces: `validate_mcp_credential_material(auth_scheme, data) -> dict[str, str]`.
- Produces: masked API field `auth_scheme` sourced from `credential_type`.

- [ ] Add failing parameterized tests for all three schemes, aliases, missing fields, extra fields, reserved header names, invalid header tokens, and control characters.
- [ ] Run from `backend/`: `../.venv/bin/pytest tests/test_credential_schema.py tests/test_credential_service.py tests/test_credential_domain_contract.py tests/test_credentials_api.py -q`; verify failures show unsupported schemes and missing response data.
- [ ] Implement the closed enum and scheme-specific material validator. `header_api_key` defaults missing `header_name` to `X-Api-Key`; `custom_header` requires it.
- [ ] Persist canonical scheme in `credential_type` on create and update, and return `auth_scheme` in masked responses without returning secret values.
- [ ] Run the focused pytest command and require all selected tests to pass.

### Task 2: Agent MCP Protocol Contract

**Files:**
- Modify: `backend/app/joysafeter_domain/schemas/joysafeter_agent.py`
- Modify: `backend/app/joysafeter_domain/agents/configuration_policy.py`
- Modify: `backend/app/joysafeter_application/agents/command_service.py`
- Modify: `frontend/types/managed.ts`
- Test: `backend/tests/test_agent_schema_contract.py`
- Test: `backend/tests/test_agent_skill_ref_gate.py`
- Test: `frontend/app/managed/agents/[agentId]/edit/page.test.tsx`

**Interfaces:**
- Produces: canonical remote transports `streamable_http` and `sse`, local transport `local_stdio`.
- Produces: remote field `auth_requirement` with `required`, `optional`, or `none`.
- Produces: `McpServerConfig.to_persisted() -> dict` containing canonical fields only.

- [ ] Add failing API schema tests proving remote/local fields are mutually exclusive, names are non-blank and unique, removed transport aliases are rejected, and new remote writes default to `required`.
- [ ] Add failing policy tests for userinfo, fragments, malformed ports, blocked literal destinations, and explicit local-stdio validation.
- [ ] Implement discriminated Pydantic models and canonical persistence values without a runtime compatibility branch.
- [ ] Update TypeScript unions to represent all transports and authentication requirements without `Record<string, unknown>` escape hatches.
- [ ] Run focused backend and frontend tests and require them to pass.

### Task 3: Selective Credential Material Resolution

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/mcp.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/record.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/access.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/store.rs`
- Test: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/mcp.rs`
- Test: `backend/app/joysafeter_orchestrator_rs/tests/credential_runtime_contract.rs`
- Test: `backend/tests/test_credential_material_access_audit.py`

**Interfaces:**
- Consumes: canonical credential scheme and material fields from Task 1.
- Produces: `resolve_mcp_member(project_id, session_id, credential_id, context)` for one selected member.
- Produces: `McpHeaderInjection { header_name, header_value, remove_headers }`.

- [ ] Add failing Rust tests for scheme-to-header mapping and all invalid header/value cases.
- [ ] Add a failing access-service test proving only the selected credential is decrypted and audited.
- [ ] Replace bulk material resolution with metadata lookup plus per-selected-id material resolution.
- [ ] Keep `Debug` implementations redacted and make audited field names exactly match fields read for each scheme.
- [ ] Run focused Cargo and Python audit tests and require them to pass.

### Task 4: Authoritative Runtime Planner

**Files:**
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_runtime_plan.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/mod.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Test: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_runtime_plan.rs`

**Interfaces:**
- Consumes: agent id, captured runtime generation, agent MCP JSON, effective network mode, bound MCP metadata, and selective credential resolver.
- Produces: `ResolvedMcpRuntimePlan::build(...) -> anyhow::Result<Self>`.
- Produces: `runner_servers() -> Vec<proto::McpConfig>` and `egress_routes() -> Vec<EgressCredentialRoute>`.

- [ ] Add failing table-driven tests covering three transports, rejection of removed aliases, required/optional/none, duplicate credentials, duplicate names, malformed persisted JSON, stable opaque route keys, path/query preservation, and secret-free debug/serialization.
- [ ] Implement typed parsing and deterministic server identity without interpolating display names into routes.
- [ ] Resolve credentials by normalized URL and enforce authentication requirement semantics before decrypting selected material.
- [ ] Make both harness input and sandbox credentials consume projections from the same plan; delete independent MCP derivation functions.
- [ ] Run the planner, harness-builder, and sandbox-resolver test subsets and require them to pass.

### Task 5: Effective Networking and SSRF Enforcement

**Files:**
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_network_policy.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`
- Modify: `backend/app/joysafeter_shared/security/ssrf_guard.py`
- Test: `backend/tests/test_mcp_url.py`
- Test: `backend/app/joysafeter_orchestrator_rs/src/kernel/mcp_network_policy.rs`
- Test: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`

**Interfaces:**
- Produces: `EffectiveNetworkMode::{Limited, Unrestricted, Disabled}`.
- Produces: `ValidatedMcpEndpoint` containing canonical authority, path, query, SNI hostname, and vetted socket addresses.

- [ ] Add failing parity fixtures for metadata, link-local, multicast, unspecified, IPv4/IPv6 literals, userinfo, fragments, ports, paths, and queries.
- [ ] Add failing networking tests proving credential-bearing remote MCP is rejected outside limited mode and remote MCP is rejected when networking is disabled.
- [ ] Implement activation-time DNS resolution and prohibited-address classification; fail if any returned address is prohibited.
- [ ] Remove real MCP hosts from `merge_mcp_hosts`; add only the placeholder host for a non-empty limited-mode remote plan.
- [ ] Render clusters from vetted addresses while preserving original authority and TLS SNI.
- [ ] Run Python/Rust URL parity and resolver tests and require them to pass.

### Task 6: Envoy Route Correctness

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`
- Test: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/tests/mcp_envoy_contract.rs`

**Interfaces:**
- Consumes: `EgressCredentialRoute` emitted only by the runtime plan.
- Produces: authority `host[:port]`, streaming-safe routes, exact header removal/injection, and per-upstream clusters.

- [ ] Add failing tests for 80, 443, 8765, and 8443 authority rendering and TLS SNI.
- [ ] Add failing tests for base-path rewriting, suffix append, query preservation, no buffering, no unsafe retries, and direct-host bypass denial.
- [ ] Render canonical authority with non-default ports and remove the generic MCP upstream from ordinary allowlist domains.
- [ ] Apply streaming route configuration to both streamable HTTP and SSE.
- [ ] Run focused lds backend and contract tests and require them to pass.

### Task 7: Runner Protocol Projection

**Files:**
- Modify: `proto/joysafeter.proto`
- Regenerate: `backend/app/joysafeter_orchestrator_rs/src/grpc/joysafeter.rs`
- Modify: `sandbox-runner/crates/joysafeter-runner/src/runner.rs`
- Modify: `sandbox-runner/crates/joysafeter-types/src/agent.rs`
- Modify: `sandbox-runner/crates/joysafeter-runtime/src/codex.rs`
- Test: `sandbox-runner/crates/joysafeter-runner/src/runner.rs`
- Test: `sandbox-runner/crates/joysafeter-runtime/src/codex.rs`

**Interfaces:**
- Consumes: runner-safe MCP projection with no credential material or original remote authority.
- Produces: `.mcp.json` entries for HTTP/SSE/local stdio and equivalent Codex runtime configuration.

- [ ] Add failing tests for all three transports, argument/environment preservation, query preservation, and absence of secrets/original authority.
- [ ] Make transport values explicit in protobuf, reserve removed field 5, and require coordinated orchestrator/runner deployment.
- [ ] Serialize remote servers as `http` or `sse` and local servers as command/args/env.
- [ ] Run runner and runtime focused tests and require them to pass.

### Task 8: ACK-Gated Lifecycle

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/sandbox/envoy.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/sandbox.rs`
- Test: `backend/app/joysafeter_orchestrator_rs/src/sandbox/lds_backend.rs`
- Test: `backend/app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs`
- Test: `backend/tests/test_credential_atomic_refresh.py`
- Test: `backend/tests/test_credential_snapshot_caller_races.py`

**Interfaces:**
- Produces: `publish_and_wait_for_ack(sandbox_id, policy, timeout) -> Result<AckedVersion, PolicyApplyError>`.
- Preserves: PostgreSQL `networking_status` and runtime generation as the execution gate.

- [ ] Add failing tests for ACK success, NACK, timeout, stale ACK, concurrent newer generation, and orchestrator restart during refresh.
- [ ] Make policy publication return the expected xDS version and wait on the existing status watch channel.
- [ ] Return command success only after ACK and durable ready-state persistence; otherwise retain pending/nacked/failed status.
- [ ] Ensure task claim/start refuses a non-ready policy even when a prior listener still exists.
- [ ] Run focused Rust lifecycle tests and Python atomic-refresh/race tests and require them to pass.

### Task 9: Frontend Complete Vertical Slice

**Files:**
- Modify: `frontend/components/managed/credentials/create-mcp-member-dialog.tsx`
- Modify: `frontend/components/managed/credentials/create-mcp-member-dialog.test.tsx`
- Modify: `frontend/app/managed/agents/[agentId]/edit/page.tsx`
- Modify: `frontend/app/managed/agents/[agentId]/edit/page.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/types/managed.ts`

**Interfaces:**
- Consumes: Task 1 credential API and Task 2 agent API.
- Produces: typed forms for transport, auth requirement, and credential scheme.

- [ ] Add failing component tests for each credential scheme, required conditional fields, each MCP transport, and payload normalization.
- [ ] Add scheme and transport selectors with conditional fields and no plaintext value persistence in query caches after successful creation.
- [ ] Add auth requirement controls defaulting new remote servers to `required`.
- [ ] Update English and Chinese copy with explicit security semantics.
- [ ] Run targeted Vitest, `bun run type-check`, and `bun run lint`.

### Task 10: Real Environment Verification

**Files:**
- Create: `backend/tests/integration/test_mcp_runtime_plan_postgres.py`
- Create: `backend/app/joysafeter_orchestrator_rs/tests/mcp_live_envoy.rs`
- Create: `docs/superpowers/evidence/2026-08-23-mcp-runtime-plan-verification.md`

**Interfaces:**
- Consumes: the complete MCP runtime path.
- Produces: repeatable PostgreSQL and Envoy evidence mapped to the specification matrix.

- [ ] Start the supported PostgreSQL/Redis/Envoy dependencies and record exact image versions and container health.
- [ ] Run migrations against a disposable PostgreSQL database and execute credential create/update/archive/restore/delete integration cases.
- [ ] Start HTTP and SSE MCP fixtures on ports 80-equivalent, 443-equivalent, 8765, and 8443; verify path, query, authority, injected headers, streaming, and direct-host denial through Envoy v1.37.1.
- [ ] Exercise required/optional/none and limited/unrestricted/disabled activation outcomes through the real planner.
- [ ] Trigger credential rotation and verify task execution stays blocked until the replacement xDS version is ACKed; verify NACK and timeout remain blocked.
- [ ] Run all focused Python, Rust, runner, frontend, formatting, lint, and type checks documented in `DEVELOPMENT.md`.
- [ ] Record commands, outputs, versions, skipped checks, and residual risks in the evidence document.
- [ ] Stop and remove all temporary MCP fixtures, Envoy/PostgreSQL containers, Docker networks, volumes created for the test, background processes, sockets, and generated scratch files; record the post-cleanup `docker ps`, network, volume, process, and `git status` evidence.

### Task 11: Completion Audit

**Files:**
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/superpowers/evidence/2026-08-23-mcp-runtime-plan-verification.md`

**Interfaces:**
- Consumes: specification requirements and all verification evidence.
- Produces: requirement-by-requirement completion table with authoritative evidence.

- [ ] Update runtime architecture diagrams and collaboration contracts to show the authoritative MCP runtime plan and ACK-gated refresh.
- [ ] Map every verification-matrix row to a test name or live command result.
- [ ] Inspect `git diff --check`, `git status --short`, and the complete diff; confirm no unrelated user changes or secret material are present.
- [ ] Mark incomplete or indirectly tested requirements as remaining risk instead of claiming completion.
