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
