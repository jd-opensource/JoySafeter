# Credential + HA Merge Repair Implementation Plan

> Execute in the existing `joysafeter-v2-0814` linked worktree. Do not commit or push.

### Task 1: Integrate latest HA safely

**Files:** conflict-dependent shared backend, frontend, Rust, and Helm files.

1. Merge `origin/joysafeter-v2-ha` with `--no-commit --no-ff`.
2. Resolve every conflict by applying the approved dual-contract rules.
3. Confirm no conflict markers remain and inspect the staged merge diff.
4. Run focused tests for each conflicted subsystem.

### Task 2: Add migration regression coverage

**Files:** `backend/tests/test_unified_credential_migration.py`, migration test helpers as needed.

1. Add a PostgreSQL test for `mcp_configs` value-preserving rename.
2. Add a test proving soft-deleted null-project credentials fail before DDL mutation.
3. Add tests for unresolved and cross-consumer references.
4. Add a duplicate-name test proving the latest row remains canonical.
5. Run each new test and verify the expected red failure.

### Task 3: Repair the forward migration

**Files:** `backend/alembic/versions/20260814_000001_unify_credentials.py`, `backend/tests/test_models/test_skill_migrations.py`.

1. Add preflight validation before creating destination tables.
2. Rename `mcp_configs` to `mcp_servers` while preserving data.
3. Correct classification and duplicate-name handling.
4. Prevent destructive teardown when references remain unresolved.
5. Make online-only and irreversible migration policy explicit in tests.
6. Run migration regression tests and `alembic check` against PostgreSQL.

### Task 4: Restore typed-ID and static correctness

**Files:** reported backend Python and orchestrator Rust files plus architecture allowlists.

1. Remove merge-introduced bare UUID entity annotations and unnecessary adapters.
2. Fix backend Ruff and Mypy errors without weakening checks.
3. Run targeted typed-ID, Ruff, and Mypy checks.

### Task 5: Clear Rust CI gates

**Files:** orchestrator and sandbox-runner files reported by rustfmt/Clippy.

1. Apply rustfmt to both workspaces.
2. Fix sandbox-runner strict Clippy errors.
3. Run both workspaces' CI-equivalent Clippy and test commands.

### Task 6: Complete full verification

**Files:** no new production scope unless a failing test identifies a merge regression.

1. Run backend full tests with PostgreSQL.
2. Run frontend full tests and production build.
3. Run pre-commit and `git diff --check`.
4. Re-run migration upgrade and schema-drift checks on fresh PostgreSQL.
5. Report remaining blockers or staging readiness with exact evidence.

### Task 7: Run pre-staging second-pass audit

**Files:** migration, HA/xDS, Helm, session pagination/cache, and rebin image files identified by the audit.

1. Fail closed on malformed legacy JSON before any schema mutation.
2. Make duplicate credential canonical selection deterministic under timestamp ties.
3. Verify xDS lease handoff, stale ownership, readiness, and shutdown ordering.
4. Verify Helm RBAC, Services, policies, checksums, and sandbox pull credentials.
5. Verify session cursor ordering, cache scope, SSE reconnect, and scroll restoration.
6. Verify rebin build contexts, copied binaries, architecture, and runtime entrypoints.
7. Add focused regressions before each fix and re-run all affected gates.
