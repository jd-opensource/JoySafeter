# Credential Material Integrity Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Follow TDD and preserve unrelated worktree changes.

**Goal:** Add an offline, read-only, bounded full-store verifier that decrypts every persisted non-empty credential ciphertext and reports only stable, non-secret failure metadata.

**Architecture:** Keep startup inventory responsible for envelope shape and configured-key coverage only. Add a focused application-layer integrity service that pages through each authoritative SQLAlchemy store in stable primary-key order, validates JSON shape before iterating fields, decrypts each material value through `VersionedMaterialProtector`, and accumulates sanitized issues. Expose it through an explicit rotation CLI mode that does not initialize canaries, rewrap data, or commit writes.

**Tech Stack:** Python 3.13, SQLAlchemy async, PostgreSQL 15, pytest, Ruff.

**Design:** `docs/superpowers/specs/2026-08-23-credential-lifecycle-integrity-and-cleanup-design.md`

## Invariants

- Verify all non-empty values in Credential `data`.
- Verify only OAuth `client_secret` and `refresh_token` values in `oauth_config`.
- Verify non-empty Task Identity `encrypted_credential` and Repository Token `encrypted_token` values, including expired rows retained in storage.
- Decrypt current-write-key envelopes instead of skipping them.
- Page by stable primary-key cursor with a positive configurable batch size; never load an entire table at once.
- Treat malformed JSON shape, non-string protected fields, unsupported/plaintext envelopes, missing keys, malformed payloads, and authentication failures as issues rather than leaked exceptions.
- Report only `surface`, `record_id`, `field`, and a stable error category. Never include plaintext, ciphertext, key bytes, or raw exception text.
- Perform no inserts, updates, deletes, canary initialization, or implicit rewrap.

---

### Task 1: Lock the Integrity Contract With PostgreSQL Tests

**Files:**
- Modify: `backend/tests/test_credential_encryption_rotation.py`

- [x] Add a regression proving envelope inventory accepts a syntactically valid active-key ciphertext whose AES-GCM tag is damaged.
- [x] Add fixtures covering Credential data, OAuth secret fields, Task Identity, and Repository Token material.
- [x] Assert the verifier detects damaged active-key ciphertext on all four surfaces.
- [x] Assert valid material crossing multiple pages is fully counted.
- [x] Assert malformed Credential JSON and non-string protected values receive stable categories.
- [x] Assert issue serialization contains no plaintext, ciphertext, or raw cryptography exception text.
- [x] Snapshot relevant rows before and after verification and assert zero database writes.
- [x] Run the focused tests and confirm the new tests fail for the missing verifier.

### Task 2: Implement the Bounded Read-Only Verifier

**Files:**
- Create: `backend/app/joysafeter_application/sensitive_material_cleanup/integrity.py`
- Modify: `backend/app/joysafeter_application/sensitive_material_cleanup/__init__.py`

- [x] Define immutable result and issue dataclasses with aggregate scanned/valid/invalid counts.
- [x] Define stable categories owned by the verifier, independent of cryptography-library messages.
- [x] Implement one cursor-paged scanner per storage surface with deterministic ordering.
- [x] Validate JSON container/value types before calling the protector.
- [x] Catch expected ciphertext/configuration/type failures at the per-value boundary and append sanitized issues.
- [x] Let database/programming failures propagate rather than misclassifying infrastructure faults as corrupt material.
- [x] Keep the session read-only by issuing only `SELECT` statements and never mutating ORM entities.
- [x] Run focused PostgreSQL tests until green.

### Task 3: Add an Explicit Offline CLI Mode

**Files:**
- Modify: `backend/scripts/credential_encryption_rotation.py`
- Modify: `backend/tests/test_credential_encryption_rotation.py`

- [x] Add `--verify-integrity` and a positive `--integrity-batch-size` option.
- [x] Route integrity mode to a separate runner that constructs the configured protector, runs the verifier, and returns JSON-safe dataclass output.
- [x] Ensure integrity mode does not validate/create canaries, rewrap, or commit.
- [x] Return a non-zero process status when integrity issues exist while still printing the sanitized report.
- [x] Reject incompatible mutating flags in integrity mode.
- [x] Add parser/runner tests for success, failure status, argument validation, and non-secret JSON output.

### Task 4: Document the Operational Boundary

**Files:**
- Modify: `SECURITY.md`
- Modify: `deploy/README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE_CN.md`
- Modify: `docs/superpowers/evidence/2026-08-22-credential-lifecycle-deep-audit.md`

- [x] State that startup inventory checks shape/envelope/key coverage but does not prove every authentication tag.
- [x] Document the offline verifier command, bounded paging, read-only behavior, covered stores, and non-zero failure status.
- [x] Document that reports contain identifiers and stable categories only.
- [x] Record real PostgreSQL verification evidence without overstating startup guarantees.

### Task 5: Verify and Clean Up

**Files:**
- Verify only; do not modify unrelated failures.

- [x] Run focused real-PostgreSQL tests for rotation and integrity verification.
- [x] Run the broader affected Python credential test matrix.
- [x] Run Ruff on changed Python files.
- [x] Run relevant Rust formatting/tests to ensure shared storage assumptions remain aligned.
- [x] Inspect the final diff for secret leakage, accidental writes, compatibility shims, and unrelated changes.
- [x] Remove disposable containers, anonymous volumes, temporary scripts, and logs created by this phase.
