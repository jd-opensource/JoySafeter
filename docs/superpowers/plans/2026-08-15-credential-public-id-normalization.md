# Credential Public-ID Normalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair every credential reference persisted as a bare UUID or legacy name and enforce canonical `cred_<uuid>` references across database, backend, Rust, and frontend boundaries.

**Architecture:** Add an atomic compensating Alembic migration that preflights all JSONB credential references before writing. Keep public-ID parsers strict, then harden backend error classification, Rust persisted-data readers, and frontend response parsing so future corruption fails explicitly.

**Tech Stack:** Python 3.13, Alembic, SQLAlchemy, PostgreSQL JSONB, Pydantic v2, Rust/sqlx/serde, React/TypeScript/Vitest.

**Spec:** `docs/superpowers/specs/2026-08-15-credential-public-id-normalization-design.md`

## Global Constraints

- Do not modify published migration `20260814_000001_unify_credentials.py`.
- Native database FK columns remain UUID; only JSONB/API values use public IDs.
- Do not weaken global `CredentialId` parsing to accept bare UUIDs.
- Complete all preflight validation before issuing any update.
- Preserve concurrent identity-federation commits and files.
- Do not commit or push unless the user explicitly requests it.

---

### Task 1: Atomic JSONB Repair Migration

**Files:**
- Create: `backend/alembic/versions/20260815_000002_normalize_credential_public_ids.py`
- Create: `backend/tests/test_credential_public_id_normalization_migration.py`
- Modify: `backend/tests/test_unified_credential_migration.py`

**Interfaces:**
- Consumes: `CredentialId.prefix == "cred_"`, PostgreSQL credential catalog.
- Produces: migration head `20260815_000002` and canonical JSONB references.

- [ ] Write failing unit tests for G0/G1/G2 classification and nested JSON preservation.
- [ ] Run the unit tests and verify failure because the migration does not exist.
- [ ] Write failing PostgreSQL tests covering environments, session snapshots, agent versions, and transaction rollback.
- [ ] Run the PostgreSQL tests and verify the old head leaves bare/legacy references.
- [ ] Implement complete preflight, row locking, prepared updates, and irreversible downgrade.
- [ ] Run migration unit and PostgreSQL tests and verify all pass.
- [ ] Update old head-level assertions to expect final canonical public IDs.
- [ ] Run `alembic heads` and verify `20260815_000002 (head)`.

### Task 2: Backend Persisted-Data Boundaries

**Files:**
- Modify: `backend/app/joysafeter_shared/common/exceptions.py`
- Modify: `backend/app/joysafeter_api/api/v1/environments.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_service.py`
- Test: `backend/tests/test_environment_credential_refs.py`
- Test: `backend/tests/test_session_credential_groups.py`
- Test: `backend/tests/test_error_contract.py` or nearest existing exception-contract module

**Interfaces:**
- Consumes: canonicalized persisted JSON from Task 1.
- Produces: server-side validation failures classified as internal corruption, and dependency scans that protect canonical references.

- [ ] Write a failing test proving persisted environment corruption is not returned as user `fix_input`.
- [ ] Write failing dependency tests for environment and frozen-session references.
- [ ] Run focused tests and verify the expected failures.
- [ ] Separate request validation from server-side Pydantic validation handling.
- [ ] Add contextual environment response failure handling only if needed after handler separation.
- [ ] Run focused backend tests and verify pass.

### Task 3: Rust Fail-Explicit Credential Readers

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/run_spec.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`

**Interfaces:**
- Consumes: canonical `cred_` JSON strings.
- Produces: contextual errors for malformed persisted IDs instead of silent omission.

- [ ] Write failing Rust tests for malformed snapshot model IDs and environment service IDs.
- [ ] Run focused Rust tests and verify current silent behavior fails assertions.
- [ ] Change snapshot resolution to distinguish null/blank from malformed IDs.
- [ ] Change environment/service reference parsing to return contextual errors.
- [ ] Propagate external-egress reference errors to the sandbox resolution boundary.
- [ ] Run focused tests, `cargo fmt -- --check`, and full `cargo test`.

### Task 4: Frontend Credential-ID Boundary

**Files:**
- Modify: `frontend/types/managed.ts`
- Modify: `frontend/lib/managed/environment-response-parsers.ts`
- Modify: `frontend/lib/managed/environment-response-parsers.test.ts`
- Test: nearest environment egress editor test module, creating one only if an established component-test location exists

**Interfaces:**
- Consumes: backend canonical public IDs.
- Produces: runtime-branded nested `CredentialId` values and compile-time `CredentialId[]` secret references.

- [ ] Write failing parser tests for bare/cross-entity nested credential IDs.
- [ ] Run focused Vitest and verify failure.
- [ ] Parse `secret_refs[]` and every egress `service_credential_id` with `parseCredentialId`.
- [ ] Change `EnvironmentConfig.secret_refs` to `CredentialId[]`.
- [ ] Run focused Vitest and TypeScript checking.

### Task 5: Deployment Gate and Final Verification

**Files:**
- Modify: `deploy/README.md`
- Modify: `deploy/helm/joysafeter-orchestrator/README.md`

**Interfaces:**
- Consumes: migration and runtime invariants from Tasks 1–4.
- Produces: operator preflight/postflight and rollback instructions.

- [ ] Document write freeze, backup, migration head, and structural zero-violation query.
- [ ] Run targeted Ruff checks.
- [ ] Run migration tests against real PostgreSQL.
- [ ] Run backend credential/environment/session regression tests.
- [ ] Run Rust format and full tests.
- [ ] Run frontend focused tests and type checking.
- [ ] Run `git diff --check` and review the final status for unrelated changes.
