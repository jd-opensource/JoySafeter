# Task 4 Implementation Report

## Status

DONE

## Revisions

- Base SHA: `3d4cef723e4387fc9a5a586dad894b573d80046f`
- Head SHA (code and tests): `ac99e0a50b0204d30e770d6b05820e0013198572`
- Implementation commit: `ac99e0a50b0204d30e770d6b05820e0013198572` (`fix(vault): reject new OAuth credential creation`)

## Files Changed

- `backend/app/joysafeter_domain/services/joysafeter_vault_service.py`
- `backend/tests/test_vault_error_contract.py`
- `.superpowers/sdd/2026-08-07-credential-domain-normalization-phase-1/task-4-report.md`

## RED Evidence

Command run from `backend/` before the service implementation:

```bash
uv run pytest tests/test_vault_error_contract.py tests/test_credential_masking_default_deny.py -q
```

Result: `4 failed, 22 passed, 21 warnings`. The failures were the three
parameterized unsupported types and the blank static Bearer token, each with
`Failed: DID NOT RAISE AppError`, proving unsupported creation was accepted.
The warnings were the documented baseline SQLAlchemy cyclic-FK warnings.

## GREEN Evidence

Initial focused command:

```bash
uv run pytest tests/test_vault_error_contract.py tests/test_credential_masking_default_deny.py -q
```

Result: `26 passed, 21 warnings`.

Final focused command:

```bash
uv run pytest tests/test_vault_error_contract.py tests/test_credential_masking_default_deny.py tests/test_secret_vault_name_soft_delete_index.py -q
```

Result: `29 passed, 24 warnings`. The warnings are the documented baseline
SQLAlchemy cyclic-FK warnings.

The first final `uv` attempt was blocked from reading the sandboxed uv cache.
Per the brief, the equivalent `backend/.venv/bin/pytest` command was attempted;
it was then blocked from the local Docker socket. The exact `uv` command was
rerun with approved local Docker/cache access and passed as recorded above.

## Requirement Mapping

1. `VaultService.create_credential` now normalizes the requested type, accepts
   only `static_bearer`, and raises `VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED` with
   the required payload for `mcp_oauth`, `oauth`, and arbitrary values.
2. Blank or whitespace-only static Bearer tokens raise
   `VAULT_CREDENTIAL_TOKEN_REQUIRED` before a credential row is inserted.
3. New rows persist the normalized static type, an encrypted trimmed token, and
   `oauth_config=None`; no OAuth configuration is stored on the new path.
4. The API route remains unchanged and thin: service errors propagate before
   its audit and network-refresh calls, which remain after successful creation.
5. Historical OAuth compatibility is preserved: tests insert an `mcp_oauth`
   row directly through the ORM, verify the GET response redacts its token, and
   verify archive and delete continue to succeed. The existing encryption test
   now creates its historical OAuth fixture directly through the ORM.
6. No migration, route, response-shape, or unrelated code changes were made.

## Concerns

None.

## Fix Round 1

### Status

COMPLETE

The requested fix commit and its follow-up tests were inspected against the
Task 4 brief. No additional code or test changes were required: all three
review findings are closed and the added assertions are valid for the current
Vault API and service lifecycle.

### Finding Dispositions

1. **Important — normalized successful creation:** CLOSED. The service change
   in `ac99e0a50b0204d30e770d6b05820e0013198572` normalizes the credential type
   and token before encryption, stores `oauth_config=None`, and rejects invalid
   input before insertion. The test added in
   `5eb1749dd88b5deb094b15ddb9f0e23c16f4f5b` creates through the API with
   surrounding whitespace and OAuth input, then queries the ORM and decrypts
   the stored token to verify `static_bearer`, the trimmed token, and
   `oauth_config is None`.
2. **Minor — historical compatibility:** CLOSED. The follow-up test is
   parameterized for both `mcp_oauth` and `oauth`, inserts each historical row
   directly through the ORM, and covers list, get/redaction, update, archive,
   restore-for-legacy-delete, and delete. No creation path is used to
   manufacture historical data.
3. **Minor — rejected API side effects:** CLOSED. The follow-up API test
   monkeypatches both `audit_joysafeter_event` and
   `refresh_live_limited_sandbox_network_policies` to fail if called, then
   submits rejected `mcp_oauth` creation and verifies the structured error.
   Since the service error propagates before those route statements, neither
   side effect runs; no route change is needed.

### Validation

Command run from `backend/`:

```bash
uv run pytest tests/test_vault_error_contract.py tests/test_credential_masking_default_deny.py tests/test_secret_vault_name_soft_delete_index.py -q
```

Result: `32 passed, 27 warnings in 11.72s`. The warnings are the existing
SQLAlchemy cyclic-FK warnings from `tests/conftest.py`.

Additional review checks:

```bash
git diff ea3ee352..5eb1749d --check
git status --short --branch
```

Both checks are clean before this report-only update.

### Files and Revisions

- Service policy: `backend/app/joysafeter_domain/services/joysafeter_vault_service.py`
- Focused lifecycle tests: `backend/tests/test_vault_error_contract.py`
- API route inspected and unchanged: `backend/app/joysafeter_api/api/v1/vaults.py`
- Final reviewed code/test head SHA: `5eb1749dd88b5deb094b15ddb9f0e23c16f4f5b`
- Fix commits: `ac99e0a50b0204d30e770d6b05820e0013198572` (service policy and
  initial coverage), `5eb1749dd88b5deb094b15ddb9f0e23c16f4f5b` (normalization,
  compatibility, and side-effect coverage)
- Report update: this section is committed separately after the fix commits.

### Concerns

None beyond the pre-existing SQLAlchemy cyclic-FK warnings noted above.
