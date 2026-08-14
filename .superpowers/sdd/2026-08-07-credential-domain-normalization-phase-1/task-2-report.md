# Task 2 Report: Unify Environment Secret Reference Extraction and Validation

## Summary

Implemented the single typed Environment Secret reference extractor and routed Environment create/update validation through it. Both direct `secret_refs` and Egress `credential_ref` values are trimmed, deduplicated by first occurrence, and validated as current-project generic Secrets. Validation errors now carry the exact reference source.

## Files

- `backend/app/joysafeter_domain/schemas/joysafeter_environment.py`
  - Added `EnvironmentSecretReferenceSource`, `EnvironmentSecretReference`, and `extract_environment_secret_references`.
  - The pure extractor accepts `EnvironmentConfig`, legacy dictionaries, or `None`; it ignores malformed legacy entries and exposes only names and sources.
- `backend/app/joysafeter_api/api/v1/environments.py`
  - Validates the unified extracted references on Environment create and config update.
  - Rejects missing references with `ENVIRONMENT_SECRET_NOT_FOUND` and non-generic references with `ENVIRONMENT_SECRET_KIND_INVALID`, including `secret_ref` and `source` data.
- `backend/tests/test_environment_egress_service_schema.py`
  - Added direct/Egress ordering, trimming, deduplication, and malformed legacy-config extraction coverage.
- `backend/tests/test_environment_lifecycle_active_sessions.py`
  - Added Egress missing-reference and both-source LLM-kind validation coverage.

## RED Evidence

1. Command:

   ```bash
   cd backend
   uv run pytest tests/test_environment_egress_service_schema.py tests/test_environment_lifecycle_active_sessions.py -q
   ```

   Output: collection failed with `ImportError: cannot import name 'EnvironmentSecretReference'`, confirming the required extraction interface was absent. The initial test setup also used a non-existent production encryption helper; it was corrected to the repository's established `credential_test_helpers.encrypted_secret_data` fixture helper before implementation.

2. Command after correcting only that test fixture import:

   ```bash
   cd backend
   uv run pytest tests/test_environment_lifecycle_active_sessions.py -q
   ```

   Output: `4 failed, 22 passed`. Failures showed the missing direct-reference `source` field, no rejection of missing Egress credentials, and no generic-kind enforcement for either source.

## GREEN Evidence

1. Command:

   ```bash
   cd backend
   uv run pytest \
     tests/test_environment_egress_service_schema.py \
     tests/test_environment_lifecycle_active_sessions.py \
     tests/test_environment_ref_boundary.py -q
   ```

   Output: `46 passed, 26 warnings in 9.04s`.

2. Command:

   ```bash
   cd backend
   uv run ruff check \
     app/joysafeter_domain/schemas/joysafeter_environment.py \
     app/joysafeter_api/api/v1/environments.py \
     tests/test_environment_egress_service_schema.py \
     tests/test_environment_lifecycle_active_sessions.py
   ```

   Output: `All checks passed!`

3. Command:

   ```bash
   git diff --check
   ```

   Output: no whitespace errors.

## Self-Review

- The extractor is pure and typed; it does not query storage, decrypt data, or expose any Secret value.
- Names are trimmed, empty legacy values are skipped, and a `seen` set preserves the first source and first-seen ordering across direct and Egress references.
- Legacy malformed values are tolerated by accepting only list-shaped reference collections and dictionary-shaped Egress services.
- Validation uses `SecretService.get_secret_by_name(..., project_id=project_id)` for every extracted reference and requires `SecretKind.GENERIC.value`.
- Both create and config-update paths pass the complete config to the shared validator.
- Scope is limited to the four Task 2 implementation/test files plus this required Task 2 report; no Secret lifecycle, Vault, frontend, or terminology changes were made.

## Concerns

- The focused database suite emits 26 existing SQLAlchemy `SAWarning` messages about unresolved metadata table sort cycles. Tests pass, and this task does not modify those models or fixture teardown behavior.
