# Credential Envelope Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize all persisted credential material to `enc:v1:`, retain transitional bare-`enc:` read compatibility, and make Python and Rust reject residual plaintext consistently.

**Architecture:** Extend the existing Python `CredentialCipher` into the authoritative Python envelope parser and reuse it from identity capture and the new Alembic normalization revision. The migration performs a full in-memory preflight over every in-scope store before issuing updates in the surrounding PostgreSQL transaction. Rust replaces passthrough behavior and caller-local prefix checks with one fail-closed decoder, while deployment documentation enforces write freeze and post-migration validation before hardening activation.

**Tech Stack:** Python 3.13, SQLAlchemy/Alembic, PostgreSQL JSONB, cryptography AESGCM, Rust, aes-gcm, sqlx, pytest, cargo test.

**Spec:** `docs/superpowers/specs/2026-08-15-credential-envelope-unification-design.md`

## Global Constraints

- Writers emit only `enc:v1:`.
- Readers accept `enc:v1:` and transitional bare `enc:`.
- Empty string is the only unencrypted sentinel.
- Non-empty plaintext, unknown envelopes, corrupt ciphertext, and non-string values fail closed.
- The migration must validate every G2/G3 value before updating any row.
- The existing `20260814_000001_unify_credentials` revision remains unchanged.
- Do not commit changes unless explicitly requested.

---

### Task 1: Python Envelope Contract

**Files:**
- Modify: `backend/app/joysafeter_shared/security/credential_cipher.py`
- Modify: `backend/tests/test_credential_cipher.py`
- Modify: `backend/tests/test_credential_cipher_contract.py`

**Interfaces:**
- Produces: `CredentialCipher.decrypt_stored(stored: str) -> str` with G2/G3/empty support.
- Produces: `CredentialCipher.normalize_stored(stored: str) -> str` for migration-safe normalization.

- [ ] Add failing tests for bare `enc:` decryption, empty sentinel, unknown `enc:v2:`, corrupt legacy payload, plaintext rejection, and normalization idempotency.
- [ ] Run the focused tests and confirm the new cases fail against the current v1-only implementation.
- [ ] Implement explicit current/legacy/unknown envelope parsing without accepting arbitrary plaintext.
- [ ] Implement `normalize_stored`: preserve empty/G3, relabel verified G2, and encrypt G1.
- [ ] Run focused Python cipher tests.

### Task 2: Python Call-Site Consolidation

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_service.py`
- Modify: `backend/app/joysafeter_api/api/v1/agent_identity_capture.py`
- Modify: `backend/tests/test_credential_service.py`
- Modify: `backend/tests/test_agent_identity_hardening.py`

**Interfaces:**
- Consumes: revised `CredentialCipher`.
- Produces: non-string storage rejection and shared identity encryption.

- [ ] Add failing service tests proving non-string stored values are rejected without `str()` coercion.
- [ ] Add a failing identity test proving `_encrypt` delegates to `CredentialCipher.encrypt`.
- [ ] Replace credential-service coercion with explicit string validation and empty handling.
- [ ] Replace inline identity AES-GCM code with `CredentialCipher`.
- [ ] Run credential-service and identity tests.

### Task 3: Atomic Normalization Migration

**Files:**
- Create: `backend/alembic/versions/20260815_000001_normalize_credential_envelopes.py`
- Modify: `backend/tests/test_unified_credential_migration.py`
- Create: `backend/tests/test_credential_envelope_normalization_migration.py`

**Interfaces:**
- Consumes: `CredentialCipher.normalize_stored` and `CredentialCipher.decrypt_stored`.
- Produces: Alembic head `20260815_000001` after `20260814_000002`.

- [ ] Update legacy migration fixtures to use real decryptable bare-`enc:` vectors.
- [ ] Add failing migration tests for mixed G1/G2/G3 in credential data, OAuth secret fields, session repo tokens, and task identity credentials.
- [ ] Add failing rollback tests for wrong key, corrupt ciphertext, unknown envelope, and non-string JSON values.
- [ ] Implement an online-only full preflight that reads and validates every row before issuing updates.
- [ ] Apply normalized JSONB/text updates without internal commits and revalidate the normalized in-memory result.
- [ ] Make downgrade explicitly unsupported and document restore-from-backup behavior.
- [ ] Run both migration test modules.

### Task 4: Rust Fail-Closed Decoder

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`

**Interfaces:**
- Produces: `VaultCipher::decrypt_envelope(&self, stored: &str) -> anyhow::Result<String>`.

- [ ] Change Rust tests first: G2 decrypts, G3 decrypts, empty returns empty, plaintext and unknown versions fail.
- [ ] Run focused Rust tests and confirm plaintext/G2 expectations fail against passthrough behavior.
- [ ] Replace `decrypt_or_passthrough` with the fail-closed decoder and update all call sites.
- [ ] Remove the agent-identity caller-local `enc:v1:` check.
- [ ] Add or update build-failure tests for residual plaintext and empty-token skipping.
- [ ] Run focused Rust cipher and harness tests.

### Task 5: Deployment Gate Documentation

**Files:**
- Modify: `deploy/helm/joysafeter-orchestrator/README.md`
- Modify: `deploy/README.md`

**Interfaces:**
- Consumes: Alembic head `20260815_000001`.
- Produces: operator sequence for backup, write freeze, migration, structural checks, cryptographic validation, and staged Rust hardening.

- [ ] Replace the stale expected Alembic head.
- [ ] Document that API, worker, orchestrator, and old HA writers must be stopped during normalization.
- [ ] Add safe structural SQL that reports classifications without revealing value prefixes.
- [ ] Document full cryptographic validation and the rollback/restore decision.
- [ ] Document mandatory rotation of credentials previously stored in plaintext.

### Task 6: Final Verification

**Files:**
- Verify all modified files.

**Interfaces:**
- Confirms the revised spec and implementation agree.

- [ ] Run Python cipher, credential-service, identity, and migration tests.
- [ ] Run Rust focused tests, then the orchestrator crate test suite if focused tests pass.
- [ ] Run formatting and `git diff --check`.
- [ ] Review the spec against the implementation for store coverage, empty semantics, and rollout ordering.
- [ ] Report unrelated pre-existing working-tree modifications separately.
