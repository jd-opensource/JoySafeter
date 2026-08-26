# Credential Key Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover all mixed-key credential material, converge runtime services on one v2 keyring, and make credential replacement recoverable without decrypting unreadable old material.

**Architecture:** A one-off transactional recovery classifies each v1 value by the recovered legacy keys and rewrites it under one v2 key ID. The credential repository then distinguishes full plaintext replacement from masked preservation, avoiding an unnecessary old-value reveal while retaining existing partial-update semantics.

**Tech Stack:** PostgreSQL 15, Python 3.12, SQLAlchemy async, FastAPI, pytest, Docker Compose, Rust orchestrator.

**Spec:** `docs/superpowers/specs/2026-08-25-credential-key-convergence-design.md`

## Global Constraints

- Do not log or persist plaintext credential values outside encrypted database fields.
- Preserve unrelated uncommitted changes.
- Do not commit unless explicitly requested.
- Run backend pytest from `backend/`.
- Stop API, worker, and orchestrator before mutating credential ciphertext.

---

### Task 1: Back Up And Migrate Credential Material

**Files:**
- Create temporarily: `/private/tmp/joysafeter-credential-key-convergence.py`
- Modify locally: ignored `.env` files used by active worktrees

**Interfaces:**
- Consumes: two recovered legacy vault keys and the active target v2 key.
- Produces: only `enc:v2:local-2026-08-25:` sensitive material plus a validated canary.

- [ ] Stop API, worker, and orchestrator containers.
- [ ] Create and validate a PostgreSQL custom-format backup.
- [ ] Run a dry-run classification requiring every value to be recoverable.
- [ ] Run the migration in one database transaction.
- [ ] Write the same keyring and write key ID to deployment environment files.
- [ ] Recreate services and verify startup canary checks.

### Task 2: Add Credential Replacement Regression Tests

**Files:**
- Modify: `backend/tests/test_credential_service.py`

**Interfaces:**
- Consumes: `UpdateCredentialRequest.data` and masked-value semantics.
- Produces: tests for full replacement and explicit partial-update failure.

- [ ] Add a test proving full plaintext replacement succeeds with unreadable old ciphertext.
- [ ] Run the targeted test and confirm it fails on the current implementation.
- [ ] Add a test proving masked preservation maps unreadable ciphertext to `CREDENTIAL_MATERIAL_UNREADABLE`.
- [ ] Run the targeted test and confirm it fails on the current implementation.

### Task 3: Implement Recoverable Update Semantics

**Files:**
- Modify: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- Modify: `backend/app/joysafeter_shared/common/error_catalog.py`

**Interfaces:**
- Consumes: a complete plaintext map or a map containing masked placeholders.
- Produces: encrypted replacement material or an actionable application error.

- [ ] Detect whether submitted data contains masked placeholders.
- [ ] Encrypt complete plaintext replacement without revealing old material.
- [ ] Preserve the existing decrypt-and-merge path for masked placeholders.
- [ ] Map unreadable old material to `CREDENTIAL_MATERIAL_UNREADABLE`.
- [ ] Run targeted credential service and API tests.

### Task 4: Verify Runtime Behavior

**Files:**
- No production file changes expected.

**Interfaces:**
- Consumes: migrated database and restarted local stack.
- Produces: evidence that model material decrypts and no-auth MCP runs without credential injection.

- [ ] Verify all sensitive material uses the active v2 key ID.
- [ ] Verify credential PATCH no longer returns `INTERNAL_ERROR`.
- [ ] Retry the reported session flow.
- [ ] Confirm no MCP credential-access audit is emitted.
- [ ] Run focused backend and Rust MCP runtime tests.
