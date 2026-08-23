# Credential Runtime Freshness and Lifecycle UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Execute task-by-task with independent review gates and strict RED → GREEN evidence.

**Goal:** Persist and expose credential-bearing runtime drift, prevent stale or mixed-generation activation, and complete MCP group/member lifecycle controls.

**Architecture:** Session snapshots remain authoritative for agent fields and the frozen non-credential environment slice, including session overlays and mounts. Only direct credential bindings and HTTP/MCP egress definitions resolve from the canonical live environment. Direct impacts advance a session desired generation and mark attached live sandboxes restart-required. Every session-bound ready write serializes on the session row before the sandbox row, task attachment checks applied equals desired, and harness materialization uses a generation seqlock. Runtime and network state remain separate in the API and UI.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, Alembic, PostgreSQL, Rust, SQLx, React 19, Next.js 16, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-credential-runtime-freshness-lifecycle-ux-design.md`

## Global Constraints

- Preserve user changes in `.deps/SkillSpector` and `backend/tests/test_rebin_dockerfiles.py`.
- Preserve `/managed/secrets`, `/managed/vaults`, existing credential APIs, and v1 identifiers.
- Do not reinterpret `networking_status` as runtime freshness.
- Do not automatically destroy `running`, `creating`, or `provisioning` runtimes.
- Use canonical environment public IDs for every new Python and Rust session creation path.
- Treat explicit missing/deleted/archived/cross-project environment bindings as terminal fail-closed.
- Preserve frozen snapshot agent fields, ordinary environment fields, session overlays, and mounts; reject credential-bearing keys in the generic overlay seam.
- Lock in deterministic order `session -> sandbox`; a plain generation comparison is not sufficient.
- Every session-bound `ready` write in Rust and Python must prove the captured generation under the session lock.
- Tasks 3A–3C are one indivisible release unit. Do not deploy or enable generation writers/live credential authority between these tasks.
- Use a coordinated migration-first deployment with activation and credential/environment writes quiesced; mixed old/new writers are unsupported.
- Add each behavior through a verified RED → GREEN cycle.
- Do not commit unless explicitly requested.

## Completed Foundation

### Task 1: Persist Runtime Configuration Freshness

- [x] Added migration `20260821_000003` and sandbox raw freshness fields.
- [x] Added schema/model coverage for `ready|restart_required`.
- [x] Verified focused migration and sandbox contract tests.

### Task 2: Mark Direct-Usage Sandboxes Restart Required

- [x] Added the runtime-configuration persistence adapter.
- [x] Routed direct and network dispositions independently in one transaction.
- [x] Marked only matching live session sandboxes stale.
- [x] Preserved network state and direct-impact atomicity.

### Task 3 R1: Preserve Freshness Across Provisioning Failures

- [x] Kept generic Python state transitions freshness-neutral.
- [x] Reset freshness only at explicit new/stopped/pool provisioning boundaries.
- [x] Preserved exact stopped-runtime freshness compensation and no-clobber behavior.
- [x] Verified focused Python and Rust lifecycle tests.

Task 3 is not architecture-complete until Tasks 3A–3C close generation, dispatch, harness, and cleanup races.

---

### Task 3A: Persist Runtime Configuration Generations

**Files:**
- Create: `backend/alembic/versions/20260821_000004_runtime_config_generation.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_session.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_sandbox.py`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/models.rs`
- Test: `backend/tests/test_unified_credential_migration.py`
- Test: `backend/tests/test_id_helper_error_contract.py`

**Interfaces:**
- Produces session desired fields: `runtime_config_generation`, `runtime_config_generation_reason`, `runtime_config_generation_updated_at`.
- Produces sandbox applied field: `runtime_config_applied_generation`.

- [ ] RED: upgrade from `20260821_000003` lacks all four columns and conservative backfill.
- [ ] Add non-null `BIGINT DEFAULT 0` desired/applied fields plus nullable session reason/time.
- [ ] Backfill sessions matching `archived_at IS NULL AND status <> 'terminated'` to desired generation `1` with migration reason/time, including idle, running, and rescheduling states.
- [ ] Keep attached non-destroyed sandboxes at applied generation `0`; preserve existing raw stale reason/time.
- [ ] Keep unattached pools raw `ready` and applied generation `0`.
- [ ] Add SQLAlchemy and Rust model fields using the exact `runtime_config_applied_generation` name.
- [ ] Verify upgrade, downgrade, defaults, nullability, active/inactive sessions, attached/destroyed/pool rows, and preserved stale markers.
- [ ] Run focused migration/model tests, Ruff, Rust formatting, and `git diff --check`.

### Task 3B: Canonicalize Binding and Advance Desired Generation

**Files:**
- Modify: `backend/app/joysafeter_infrastructure/runtime_configuration/status.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/network_policy_adapter.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- Modify: `backend/app/joysafeter_application/credentials/ports.py`
- Modify: `backend/app/joysafeter_application/credentials/resource_service.py`
- Modify: `backend/app/joysafeter_application/credentials/snapshot_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_environment_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_session_service.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/snapshot_adapter.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/snapshot.rs`
- Test: `backend/tests/test_environment_credential_refs.py`
- Test: `backend/tests/test_credential_atomic_refresh.py`
- Test: `backend/tests/test_credential_application_boundaries.py`
- Test: `backend/tests/test_credential_snapshot_caller_races.py`
- Test: `backend/tests/test_environment_ref_boundary.py`
- Test: `backend/tests/test_credential_snapshot_linearization.py`
- Test: `backend/app/joysafeter_orchestrator_rs/tests/credential_snapshot_linearization.rs`

**Interfaces:**
- Produces one direct/egress/mixed mutation disposition computed from the live credential-bearing slice.
- Produces canonical environment public IDs for all new Python and Rust sessions.
- Preserves the frozen snapshot slice, session overlays, and mounts.

- [x] RED: direct credential-reference and directly referenced credential mutations do not advance affected session generations.
- [x] RED: Rust scheduler name input persists the original name instead of the locked environment public ID.
- [x] RED: credential rename-only, empty patch, equal-value update, and environment creation emit spurious runtime/network impacts.
- [x] Lock affected active session rows in deterministic ID order, advance each generation once, then mark live sandboxes stale under `session -> sandbox` order.
- [x] Write session generation reason/time in the same transaction as resource mutation, audit, stale marking, and any network disposition.
- [x] Keep egress-only changes generation-neutral and route them through existing network refresh.
- [x] Preserve the existing project-scoped conservative egress refresh; exact egress targeting is not part of this task.
- [x] Execute both branches for mixed direct-plus-egress changes; semantic no-ops execute neither.
- [x] Aggregate one logical resource mutation into one combined impact and defensively deduplicate direct generation advancement per session within the UoW.
- [x] Recompute direct/egress usage on credential restore; retain P0 archive/delete dependency blocking and produce no generation write for rejected or unreferenced lifecycle changes.
- [x] Treat environment creation and successful unreferenced environment archive/delete as generation/network no-ops; environment restore is not implemented by this plan.
- [x] Resolve credential impact usage from canonical live direct/egress bindings only; retain snapshot fallback solely for legacy sessions with no binding.
- [x] Restrict `environment_config_overlay` to an explicit frozen-key allowlist and reject direct, egress, legacy alias, mixed, and future decoder-recognized credential-bearing fields.
- [x] Canonicalize environment name/ID input after the locked environment re-read in Python Session API/service, task/trigger creation paths, and Rust scheduler snapshot creation.
- [x] Resolve legacy non-ID session bindings by unique exact-project name without snapshot fallback; use the canonical ID for runtime decisions and optionally persist it under the session lock.
- [x] Prove ID/name equivalence, exact/null-safe project scope, active lifecycle, one bump per session, sessions without sandboxes, no-op behavior, and rollback atomicity.
- [x] Add a real two-connection barrier proving affected sessions are locked in deterministic ID order and concurrent direct mutations serialize without deadlock or lost bumps.
- [x] Prove frozen-only overlay acceptance, credential-bearing overlay rejection, typed mount preservation, and cross-session overlay isolation.
- [x] Preserve P0 snapshot lifecycle blockers and credential lock-linearization tests.
- [x] Run focused Python/Rust tests, Ruff, Rust formatting, and `git diff --check`.

### Task 3C: Fence Activation, Dispatch, and Harness Materialization

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/sandbox.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/task.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/models.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/run_spec.rs`
- Create: `backend/app/joysafeter_orchestrator_rs/src/kernel/runtime_freshness.rs` if no existing typed-error module is a better fit.
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/grpc/server.rs` only if the builder cannot fully own the SetupSandbox/StartTask fence.
- Modify: `backend/app/joysafeter_domain/services/joysafeter_sandbox_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/tasks.py`
- Modify: `backend/app/joysafeter_domain/services/agent_trigger_execution.py`
- Test: `backend/app/joysafeter_orchestrator_rs/tests/credential_store_integration.rs`
- Test: colocated Rust resolver, scheduler, gRPC, and harness tests.
- Test: `backend/tests/test_sandbox_state_machine_contract.py`
- Test: existing task API tests for explicit invalid session bindings and replay.
- Test: existing trigger execution tests for pinned/reuse/keyed invalid bindings.

**Interfaces:**
- Produces session-row-serialized new/stopped/pool ready writers with `runtime_config_applied_generation`.
- Produces task-attach freshness fencing and harness generation seqlock.
- Produces typed `GenerationChanged`, `RuntimeRestartRequired`, `SessionBindingInvalid`, `Conflict`, and `CleanupFailed` outcomes.

- [x] RED: double-connection barriers reproduce false-ready races for new, stopped, and pool paths in both lock acquisition orders.
- [x] RED: mutation between resolver success and task attach permits stale attachment.
- [x] RED: mutation during harness materialization can mix old runtime state with new credential material.
- [x] Capture desired generation with the frozen snapshot plus live credential-bearing resolve context.
- [x] Lock session first, validate lifecycle/project/generation, then lock or insert sandbox for every Rust ready writer.
- [x] Apply the same guard to Python create, stopped activation, and pool attachment while keeping generic FSM transitions freshness-neutral.
- [x] Keep unattached pool reservation neutral; atomically attach session/project/fingerprint/ready/applied-generation/timestamps at guarded activation.
- [x] Extend stopped claim tokens and compensation predicates with previous/current applied generation for exact restore and ABA/no-clobber protection.
- [x] Fence task attachment on raw `ready`, applied equals desired, valid ownership, and active lifecycle.
- [x] Preserve the lock order `session -> sandbox -> task` for guarded attachment.
- [x] Implement harness read-materialize-reread seqlock using sandbox ID and require stable desired/applied generation plus raw `ready`.
- [x] Return typed `RuntimeRestartRequired` for stale active runtimes without provider destroy; define scheduler/task state and no-retry behavior.
- [x] Prove `Stop Session` followed by the next explicit task activation replaces/reprovisions the stale runtime and clears freshness only after the guarded ready write.
- [x] Bound `GenerationChanged` retries and fall back to scheduler backoff rather than permanent failure.
- [x] On rejected new activation, require successful provider teardown before retry; cleanup failure stops retries.
- [x] Add conditional attached-pool compensation. Cleanup failure leaves the sandbox attached and non-ready for reconciliation and never creates a second runtime.
- [x] Verify explicit invalid binding is terminal, project checks are null-safe, and no guarded failure writes `ready`.
- [x] Verify existing-session task submission and keyed trigger reuse do not fall back from an explicit invalid session binding to the current agent/trigger environment.
- [x] Verify pinned and direct reusable trigger sessions follow the same explicit-binding fail-closed rule.
- [x] Run focused SQLx/PostgreSQL barrier tests, resolver/scheduler/harness tests, Python parity tests, Rust formatting, Ruff, and `git diff --check`.

### Task 3D: Atomic Release Gate

**Files:**
- Modify: deployment/runbook documentation selected by the repository conventions.
- Test: release compatibility checks or smoke scripts selected during implementation.

**Interfaces:**
- Prevents old unguarded runtime writers/readers from serving alongside generation-enabled writers.

- [ ] Document: quiesce activation and credential/environment writes → migrate → deploy all Python/Rust Task 3A–3C code → resume traffic.
- [ ] Add an explicit startup/schema compatibility assertion if an existing mechanism supports it; do not invent a parallel feature-flag system without evidence.
- [ ] Verify old binaries are not part of the supported rollout and generation writers cannot be enabled independently.
- [ ] Record operational rollback: stop traffic, restore compatible binaries, downgrade only after generation-aware writers are stopped.

### Task 4: Add Effective Session Runtime Status API

**Files:**
- Create: `backend/app/joysafeter_domain/schemas/joysafeter_runtime_status.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Create: `backend/tests/test_session_runtime_status_api.py`
- Test: existing network-policy API contract tests discovered during implementation.

**Interfaces:**
- Produces `GET /sessions/{session_id}/runtime-status` as an object for every accessible session.
- Returns effective runtime freshness and the existing session-page network summary, including policy hash.

- [ ] RED: cover raw-ready/equal, raw-ready/mismatch, raw-stale/equal, raw-stale/mismatch, stopped, destroyed, no-sandbox, cross-project, and super-user cases.
- [ ] Derive effective `restart_required` when raw status is stale or applied differs from desired.
- [ ] Use sandbox reason/time for raw stale and session generation reason/time for generation-only mismatch.
- [ ] Return an object with nullable sandbox/runtime/network fields when no non-destroyed sandbox exists; never return a bare JSON `null`.
- [ ] Include `networking_status`, policy version, policy hash, last error, and ready timestamp.
- [ ] Keep `/network-policies/sessions/{session_id}` behavior and response shape unchanged.
- [ ] Run focused API authorization and network compatibility tests.

### Task 5: Surface Runtime Restart Requirement

**Files:**
- Modify: `frontend/types/managed.ts`
- Create: `frontend/lib/managed/runtime-status-response-parsers.ts`
- Create: `frontend/lib/managed/runtime-status-response-parsers.test.ts`
- Modify: `frontend/app/managed/sessions/[sessionId]/page.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Test: `frontend/app/managed/sessions/[sessionId]/page.scope.test.ts`

**Interfaces:**
- Consumes `GET /sessions/{session_id}/runtime-status`.
- Produces separate runtime-configuration warning, no-sandbox state, and network-policy status rendering.

- [ ] RED: parser and page tests cover effective restart-required, generation reason/time, full network summary, and nullable no-sandbox fields.
- [ ] Switch the session page query to the runtime-status endpoint.
- [ ] Explain that new credential values apply after stopping the session and starting the next task, which performs guarded runtime recreation/reprovisioning.
- [ ] Keep runtime drift visually and semantically separate from network-policy failures.
- [ ] Add English and Chinese copy.
- [ ] Run focused Vitest, TypeScript, ESLint, and production build checks.

### Task 6: Complete MCP Group Lifecycle UI

**Files:**
- Modify: `frontend/components/managed/credentials/mcp-vault-list.tsx`
- Modify: `frontend/components/managed/credentials/mcp-vault-detail.tsx`
- Modify: `frontend/components/managed/credentials/mcp-vault-list.test.tsx`
- Modify: `frontend/components/managed/credentials/mcp-vault-detail.test.tsx`
- Modify: `frontend/app/managed/vaults/vault-member-lifecycle.test.ts`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

**Interfaces:**
- Consumes existing group restore, credential restore, group-member delete, and group delete endpoints.

- [ ] RED: archived group restore/delete in list and detail views.
- [ ] RED: archived-member restore/delete while parent active and disabled actions while parent archived.
- [ ] Preserve project read-only and stale-scope guards.
- [ ] Keep restored group members archived until explicitly restored.
- [ ] Run credential parity and full frontend tests.

### Task 7: Full Verification and Documentation Closure

**Files:**
- Modify: `docs/superpowers/specs/2026-08-21-credential-runtime-freshness-lifecycle-ux-design.md`
- Modify: `docs/superpowers/plans/2026-08-21-credential-runtime-freshness-lifecycle-ux.md`
- Modify: `.superpowers/sdd/2026-08-21-credential-runtime-freshness-lifecycle-ux/task-3-report.md`

- [ ] Mark contradictory pre-R1 Task 3 passages as historical without rewriting evidence.
- [ ] Run Alembic head, upgrade-from-`000003`, downgrade, and backfill verification.
- [ ] Run focused credential, environment, sandbox, session, runtime-status, and P0 lifecycle pytest suites.
- [ ] Run Rust generation barriers, snapshot linearization, resolver, scheduler, harness, gRPC, and credential-store tests plus `cargo fmt --check`.
- [ ] Run frontend targeted tests, full Vitest, TypeScript, ESLint, and production build.
- [ ] Run rollout smoke/compatibility checks and confirm unsupported mixed-version state cannot serve traffic.
- [ ] Run `git diff --check` and confirm preserved user files were not altered by this plan.
- [ ] Request final architecture and code review before declaring completion.
