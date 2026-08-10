# Final Security-Boundary Fix Report

**Branch:** `credential-domain-normalization-phase-1`
**Review base:** `4aa37e4c6826708e845e51c86e48a6b598f55b98`
**Implementation head before this report:** `cf437c3f9afbcc33dc8dd7e70580e8e9cfe340e5`

## Status

The security-boundary wave resolves the reviewed `1 Critical`, `1 Important`, and `2 Minor` findings. The implementation adds no migration, route rename, wire-field rename, entity-type rename, OAuth expansion, or plaintext exposure.

## Critical: Blank Webhook Credential

### Threat model and reproduction

A historical or malformed Generic Secret could contain a selected Webhook field whose decrypted value normalized to blank. Webhook authentication previously checked only that the selected key existed and returned the empty string. Because an HMAC-SHA256 key of `""` is public and deterministic, an unauthenticated caller could calculate the expected signature and invoke the public Webhook route.

The regression creates the historical Secret and Trigger through the ORM, signs a real request body with `WebhookAuthService.sign('', body)`, and posts it through `/api/v1/triggers/{trigger_id}/webhook`. The vulnerable flow accepted that signature during RED. The corrected flow rejects it before `fire_webhook` can run.

### Resolution and error contract

- `WebhookAuthService.resolve_secret_value` now requires the selected decrypted value to be nonblank after `strip()` inspection.
- Nonblank values are returned unchanged; this preserves existing request normalization, encryption, and decryption behavior without exposing plaintext.
- Create and update validation raise `RequestValidationAppError` with stable code `TRIGGER_SECRET_VALUE_BLANK`, message `Webhook credential field must not be blank`, and `user_action="fix_input"`.
- Create error data contains only `secret_ref` and `secret_key`; update also carries the existing `trigger_id` context.
- The code is registered in the shared error catalog.
- The public Webhook route includes the code in its secret-resolution sanitization set. Historical malformed rows therefore return only `TRIGGER_WEBHOOK_UNAUTHORIZED`, the generic message, and empty data. Secret name, selected key, value, and Trigger ID are not disclosed.
- Create and update regressions prove rejection before persistence and scheduler notification. The public-route regression proves that the known empty-key HMAC cannot fire the Trigger.

The check is intentionally local to Webhook authentication resolution. Unrelated Secret fields are not globally prohibited from containing blank values.

## Important: Secret Resource Names

### Canonical request and persistence policy

- `CreateSecretRequest.name` and optional `UpdateSecretRequest.name` trim leading and trailing whitespace at the request-model boundary.
- Empty and whitespace-only names use the existing structured `REQUEST_VALIDATION_ERROR` response before service persistence or API side effects.
- Create and update explicitly persist the normalized name, so padded input is stored and returned canonically.
- Canonical uniqueness is checked before update mutation and still guarded by database integrity handling. Normalized create/update collisions return the existing `SECRET_NAME_EXISTS` contract with the canonical name in error data.
- Rejected create/update requests leave encrypted data and resource names unchanged and do not emit audit or live-network refresh side effects.

### Historical compatibility and selector policy

- General Connections & Credentials list parsing preserves historical names exactly, including blank and padded values, so malformed rows remain visible for cleanup.
- Historical padded rows remain listable and can be renamed to a canonical name through the normal update path.
- A shared selector-boundary predicate accepts a resource name only when it is nonempty and exactly equal to `name.trim()`.
- The Service Credential query, Service Credential selector, and Environment Egress editor all apply that predicate. This prevents empty Radix values and padded wire references while leaving management pages unchanged.
- Tests cover management-parser preservation, shared filtering, query filtering, both selectors, Egress rendering, create/update canonical persistence, normalized conflicts, no-side-effect rejection, and historical rename cleanup.

## Minor: Skill-Import Inventory

- The finite error-code-to-translation maps now live as exported production constants in `frontend/lib/managed/skill-import.ts`; presenters consume those same maps.
- `MANAGED_SKILL_IMPORT_RUNTIME_TRANSLATION_KEYS` is derived from the production map values and deduplicated. There is no second manually maintained translation-key map.
- Active translation inventory consumes that production-derived key set as the `skillImport` finite family.
- The family contains `15` unique runtime keys and adds no duplicate active leaves.
- A mutation regression deletes `managed.skills.zipErrors.pathUnsafe` from both catalogs and directly requires both missing-key lists to report that exact runtime key.
- Final active counts are `1273` direct, `387` dynamic, and `1660` total. No newly exposed active key is missing, and no legacy value required replacement.

## Minor: Quickstart Step 2

Production behavior advances Model Connection selection to step 3 and renders the compact badge `Model Connection Selected: <name>`. It does not render a step-2 `StepCompleteCard` description.

The minimal behavior-preserving correction:

- Limits semantic `StepCompleteCard` completion steps to `3`, `4`, `5`, and `6`.
- Uses a runtime type guard instead of casting an arbitrary current step into the semantic mapping.
- Removes the dead step-2 description from both locale catalogs and active terminology expectations.
- Keeps the approved compact Model Connection badge wording and all step `3`-`6` title/description mappings intact.
- Adds a page-level regression for the real step-3 badge and verifies that neither dead copy nor a raw translation key is rendered.

## TDD RED/GREEN

Focused RED/GREEN cycles were run before the final suites:

1. **Webhook boundary**
   - RED: create/update accepted selected blank values, and the public route accepted an HMAC generated with the known empty key.
   - GREEN: create/update return `TRIGGER_SECRET_VALUE_BLANK` without persistence or scheduler notification; the actual public route returns generic unauthorized and never fires.
2. **Secret names and selectors**
   - RED: blank/padded request names were not canonically enforced, normalized collisions were not handled on update, and historical malformed names remained selectable.
   - GREEN: request, persistence, conflict, no-side-effect, management compatibility, shared filter, query, selector, and Egress regressions pass.
3. **Skill-import inventory**
   - RED: deleting `managed.skills.zipErrors.pathUnsafe` from both catalogs did not put it in either missing-key list.
   - GREEN: production-derived finite inventory reports the exact missing key in both catalogs; restored catalogs have no missing leaves.
4. **Quickstart semantics**
   - RED: step 2 remained in the semantic completion mapping and dead description inventory even though the page rendered only the compact badge.
   - GREEN: semantic mapping is `3`-`6`, dead copy is absent, and the page-level badge regression passes with approved terminology.

## Verification

### Backend

- Affected regression selection: `62 passed`, `61` existing SQLAlchemy dependency-cycle warnings.
- Exact 16-file Task 8 suite: `214 passed`, `155` existing SQLAlchemy dependency-cycle warnings.
- A broad run of the five changed backend test files produced `68 passed` and one unrelated failure: `test_initial_schema_remains_the_only_alembic_head` expects `20260803_000001`, while this branch already has Alembic head `20260807_000002`. The affected-test selection above excludes only that stale assertion.

### Frontend

- Expanded 22-file suite covering Trigger UI/contracts, Secret contracts, Service Credential query/selector, Egress, skill-import inventory, Quickstart page/helper/hooks, Vault compatibility, and terminology: `22 passed` files, `520 passed` tests.
- `bun run type-check`: exit `0`, no diagnostics.
- `bun run lint`: exit `0`, `0` errors and the established `692`-warning baseline; `609` warnings are potentially fixable.

### Range and compatibility

- `git diff --check`: exit `0` before implementation commits and on the clean implementation worktree.
- `git diff --check 4aa37e4c6826708e845e51c86e48a6b598f55b98..cf437c3f9afbcc33dc8dd7e70580e8e9cfe340e5`: exit `0`.
- The implementation range contains `27` changed files, `777` insertions, and `75` deletions.
- No path under `backend/alembic` changed.
- No route decorator changed.
- `secret_ref`, `secret_key`, `credential_ref`, `vault_ids`, resource-ID formats, and existing entity names are preserved.
- Service Credential and Egress selector paths contain no `secret_data` access.
- Vault Credential creation still contains no `mcp_oauth` or OAuth branch, and no authorization, callback, refresh, or token-exchange behavior was added.
- Historical management visibility and historical OAuth compatibility remain unchanged.

The backend error-catalog guard now excludes `TRIGGER_SECRET_VALUE_BLANK` from its missing set. It still reports `11` pre-existing branch codes that are absent from the catalog: `ENVIRONMENT_SECRET_KIND_INVALID`, `QUICKSTART_BASE_URL_REQUIRED`, `QUICKSTART_PROTOCOL_UNSUPPORTED`, `QUICKSTART_SECRET_INCOMPATIBLE`, `SECRET_TEST_BASE_URL_REQUIRED`, `SECRET_TEST_CREDENTIAL_PROFILE_UNSUPPORTED`, `SKILL_AUTHORING_BASE_URL_REQUIRED`, `SKILL_AUTHORING_SECRET_INCOMPATIBLE`, `TRIGGER_SECRET_KIND_INVALID`, `VAULT_CREDENTIAL_TOKEN_REQUIRED`, and `VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED`.

## Commits

- `6827808481fb21367b7f7a579c140da03bd4db7a` — `fix(trigger): reject blank webhook credentials`
- `19bfa565b5d64261c5fc0bd1cfca1e9206df4032` — `fix(secrets): canonicalize selectable resource names`
- `bc90557af10e50e264607ae1547de9e85809d7a1` — `test(i18n): inventory skill import runtime keys`
- `cf437c3f9afbcc33dc8dd7e70580e8e9cfe340e5` — `fix(quickstart): align completion copy with runtime`
- Final report commit: committed separately and identified in the handoff.

## Concerns

1. The exact backend suite passes but continues to emit the existing SQLAlchemy foreign-key-cycle warning from `backend/tests/conftest.py:148`.
2. Frontend lint retains the established `692` warnings with zero errors; this wave does not expand that baseline.
3. The branch-wide error-catalog guard retains the `11` pre-existing missing codes listed above; the new Webhook code is registered and is not among them.
4. `test_initial_schema_remains_the_only_alembic_head` is stale against the branch's existing `20260807_000002` Alembic head. This wave adds no migration and does not change that existing head.

No reviewed security-boundary finding remains unresolved.
