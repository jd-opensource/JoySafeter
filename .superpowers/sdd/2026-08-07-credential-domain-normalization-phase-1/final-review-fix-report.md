# Credential Domain Normalization Phase 1 Final-Review Fix Report

**Status:** DONE_WITH_CONCERNS
**Verification date:** 2026-08-10
**Workspace:** `/Users/yuzhenjiang1/Downloads/workspace/JoySafeter/.worktrees/credential-domain-normalization-phase-1`
**Branch:** `credential-domain-normalization-phase-1`
**Fix base SHA:** `3f48a4e2bc8dc3a91a180f7c4c8bdd05df4d3d18`
**Implementation HEAD before this report commit:** `c595544a53c2cdc8d846a787bccd410154c9fe64`

## Root-Cause Evidence Recorded Before Changes

### 1. Public Webhook Error Sanitization

- The unauthenticated Webhook route catches resolver errors in `backend/app/joysafeter_api/api/v1/triggers.py` and converts only codes in `_WEBHOOK_SECRET_RESOLUTION_ERROR_CODES` to the generic `TRIGGER_WEBHOOK_UNAUTHORIZED` response.
- `git blame` shows the allowlist was introduced by `677a694384087d9f36e40794a255afa2d5b6254e` with `TRIGGER_SECRET_REF_REQUIRED`, `TRIGGER_SECRET_NOT_FOUND`, and `TRIGGER_SECRET_KEY_NOT_FOUND`.
- Phase commit `c3f4034b57bd7f7610696ba34e7a04b4a197a17d` added `TRIGGER_SECRET_KIND_INVALID` in `WebhookAuthService.resolve_secret_value`, including `secret_ref`, `trigger_id`, and `kind` metadata, but did not update the public-route allowlist or its sanitization regression test.
- Historical Trigger rows can reference an LLM Secret because they bypass current create/update validation. Runtime resolution therefore raises the new code at the public route, where the allowlist miss allows the detailed error envelope to reach an unauthenticated caller.
- Root cause: a security-boundary allowlist was duplicated separately from the resolver error family and drifted when the family gained a new member.

### 2. Environment Direct `secret_refs` Normalization

- `EnvironmentConfig.secret_refs` is declared as `list[str]` with no field validator. In contrast, `EgressService.credential_ref` has a `mode="before"` validator that trims and rejects blank input.
- Phase commit `95d0f739c9921cbebf5618fedbc7ccb288e68e75` added `extract_environment_secret_references`. The extractor trims direct references and ignores empty historical values so validation and lifecycle scans remain tolerant.
- API validation consumes the extractor, so a whitespace-padded direct reference is looked up under its trimmed name and a blank direct reference disappears from validation entirely.
- `EnvironmentService.create_environment` and `update_environment` persist `req.config.model_dump()`, which still contains the original direct-reference strings. Exact Rust runtime lookup therefore receives padded names, while blank direct refs can be stored.
- Root cause: tolerant read-time canonicalization was used for request validation, but request-model normalization was never added at the write boundary.

### 3. Remaining Active Credential Terminology

- Phase commit `18afd5762fb8a7ead811a546992aab825f90632e` normalized selected locale paths, and `855ecf5e06e247029dbb39e6b4d2e1143f8d5f1f` expanded a table-driven contract around those selected paths.
- The phase did not inventory production call sites before defining that contract. Active paths omitted from it still contain legacy terms.
- Production evidence includes agent create/edit labels and compatibility states, the compatible Model Connection picker, Secret detail/create states, Session MCP empty/search states, MCP Credential Set list/create/detail copy, and the dynamic `managed.errorStates.vault.*` paths selected by `ResourceErrorState` when both Vault pages pass `resource="vault"`.
- Direct searches show old catalog keys such as `agents.edit.selectSecret`, `managed.agents.edit.selectSecret`, and `managed.triggers.secretRefPlaceholder` have no production call sites; they are intentionally outside this fix.
- Root cause: the terminology contract mirrored the first replacement list rather than the full set of active credential-domain rendering paths, so active omissions were not protected against legacy vocabulary.

## RED Test Design

- Public Webhook route: seed a historical Webhook Trigger referencing an LLM Secret and assert the unauthenticated response is generic and contains neither the Secret name nor `kind` metadata.
- Environment requests: assert create and update persist trimmed direct refs, both request models reject blank direct refs, and historical dictionary extraction remains tolerant.
- Terminology: extend the table-driven bilingual contract with every active omitted path and exact approved copy, while leaving inactive legacy catalog keys unchanged.

## RED/GREEN Evidence

### RED 1: Public Webhook Invalid-Kind Sanitization

```bash
cd backend
uv run pytest tests/test_trigger_webhook_route_contract.py::test_webhook_route_hides_historical_invalid_secret_kind_from_public_callers -q
```

- Exit status: `1`.
- Result: `1 failed, 1 warning`.
- Expected failure: the public response exposed `code='TRIGGER_SECRET_KIND_INVALID'` instead of returning `TRIGGER_WEBHOOK_UNAUTHORIZED`.
- The warning was the existing SQLAlchemy FK-cycle `SAWarning` from `backend/tests/conftest.py:148`, not a test error.

### RED 2: Environment Direct-Reference Normalization

```bash
cd backend
uv run pytest \
  tests/test_environment_egress_service_schema.py \
  tests/test_environment_lifecycle_active_sessions.py::test_create_environment_persists_trimmed_direct_secret_refs \
  tests/test_environment_lifecycle_active_sessions.py::test_update_environment_persists_trimmed_direct_secret_refs -q
```

- Exit status: `1`.
- Result: `4 failed, 11 passed, 2 warnings`.
- Expected failures: both create/update request models accepted a blank direct ref, and both create/update responses retained whitespace around the direct ref instead of returning the canonical Secret name.
- The two warnings were the same existing SQLAlchemy FK-cycle `SAWarning`; there were no collection or fixture errors in the final RED run.
- `test_extract_environment_secret_references_tolerates_legacy_malformed_config` passed in this RED run, establishing the historical-dictionary compatibility baseline before the request-model fix.

### RED 3: Active Credential Terminology Paths

```bash
cd frontend
bun run test -- lib/i18n/credential-terminology.test.ts
```

- Exit status: `1`.
- Result: `1` test file failed; `64 failed, 219 passed` assertions.
- Expected failures: all `32` newly enumerated active paths failed in both English and Chinese, exposing the remaining Model Configuration/模型配置 and Vault/凭证库 copy.
- The failing paths cover agent create/edit, Model Connection picker/help/empty/error states, Session MCP empty states, MCP Credential Set list/create/detail copy, and dynamic MCP resource error states.

### GREEN 1: Public Webhook Invalid-Kind Sanitization

```bash
cd backend
uv run pytest tests/test_trigger_webhook_route_contract.py -q
```

- Exit status: `0`.
- Result: `8 passed, 8 warnings` in `5.25s`.
- The historical LLM-Secret route case now returns `TRIGGER_WEBHOOK_UNAUTHORIZED` with `data={}` and contains neither the Secret name, a `kind` field, nor the `llm` value.
- All warnings were the existing SQLAlchemy FK-cycle `SAWarning` family.

### GREEN 2: Environment Direct-Reference Normalization

```bash
cd backend
uv run pytest \
  tests/test_environment_egress_service_schema.py \
  tests/test_environment_lifecycle_active_sessions.py::test_create_environment_persists_trimmed_direct_secret_refs \
  tests/test_environment_lifecycle_active_sessions.py::test_update_environment_persists_trimmed_direct_secret_refs -q
```

- Exit status: `0`.
- Result: `15 passed, 2 warnings` in `3.51s`.
- Create and update return and persist the canonical trimmed Secret name.
- Both request models reject a blank direct ref.
- Historical malformed-dictionary extraction remains tolerant and passed unchanged.
- Both warnings were the existing SQLAlchemy FK-cycle `SAWarning` family.

### GREEN 3: Active Credential Terminology Paths

```bash
cd frontend
bun run test -- lib/i18n/credential-terminology.test.ts
```

- Exit status: `0`.
- Result: `1/1` file and `283/283` assertions passed.
- The table now pins exact approved English and Chinese copy for all `32` newly inventoried active paths.

## Files

- `backend/app/joysafeter_api/api/v1/triggers.py` — adds `TRIGGER_SECRET_KIND_INVALID` to the public Webhook sanitization boundary.
- `backend/tests/test_trigger_webhook_route_contract.py` — covers a historical invalid-kind Trigger through the real resolver and public route.
- `backend/app/joysafeter_domain/schemas/joysafeter_environment.py` — canonicalizes direct refs on Create/Update request models and rejects blanks while leaving the historical extractor tolerant.
- `backend/tests/test_environment_egress_service_schema.py` — covers blank rejection for both request models and retains malformed historical extraction coverage.
- `backend/tests/test_environment_lifecycle_active_sessions.py` — covers trimmed create/update persistence.
- `frontend/lib/i18n/credential-terminology.test.ts` — adds bilingual expectations for active omitted credential-domain paths.
- `frontend/lib/i18n/locales/en.ts` — normalizes active English Model Connection, MCP Credential Set, and Project Access Token copy.
- `frontend/lib/i18n/locales/zh.ts` — normalizes the matching active Chinese copy.
- `.superpowers/sdd/2026-08-07-credential-domain-normalization-phase-1/final-review-fix-report.md` — records investigation, TDD, verification, dispositions, and concerns.

## Finding Dispositions

### 1. Public Webhook Error Sanitization — FIXED

- Added `TRIGGER_SECRET_KIND_INVALID` to `_WEBHOOK_SECRET_RESOLUTION_ERROR_CODES` at the unauthenticated route boundary.
- Added a historical Trigger fixture by inserting the Trigger and LLM Secret directly through the ORM, so current create validation cannot hide the compatibility scenario.
- The regression asserts the public response is the generic unauthorized envelope and does not contain the Secret name, `"kind"`, or `llm` metadata.

### 2. Environment Direct `secret_refs` Normalization — FIXED

- Added one request-boundary canonicalizer reused by `CreateEnvironmentRequest.config` and `UpdateEnvironmentRequest.config` validators.
- The canonicalizer trims every direct ref, rejects blank entries, and returns a copied config before `EnvironmentService` calls `model_dump()` for persistence.
- Focused create/update tests inspect both response models and stored JSON rows.
- `extract_environment_secret_references` remains unchanged; malformed historical dictionaries still ignore empty/invalid entries without crashing lifecycle scans.

### 3. Remaining Active Credential Terminology — FIXED

- Traced direct and dynamic production call sites before changing copy.
- Added exact bilingual contract rows for `32` active omitted paths covering agent create/edit, compatible Model Connection selection and states, Secret create/detail states, Session MCP empty states, MCP Credential Set list/create/detail copy, and dynamic MCP resource error states.
- Updated only those active values. Internal i18n keys, routes, API fields, and TypeScript types are unchanged.
- A post-fix legacy-term scan leaves only `agents.edit.selectSecret`, `agents.edit.createSecret`, `managed.agents.edit.selectSecret`, `managed.agents.edit.createSecret`, and `managed.triggers.secretRefPlaceholder` in each locale; direct production searches found no call sites for these inactive keys, so they were intentionally not changed.

## Regression, Static, and Boundary Results

### Coordinated Targeted Suites

Backend:

```bash
cd backend
uv run pytest \
  tests/test_trigger_webhook_route_contract.py \
  tests/test_environment_egress_service_schema.py \
  tests/test_environment_lifecycle_active_sessions.py \
  tests/test_environment_ref_boundary.py -q
```

- Exit status: `0`.
- Result: `58 passed, 36 warnings` in `12.00s`.
- All warnings were the existing SQLAlchemy FK-cycle `SAWarning` family.

Frontend:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  components/managed/llm/compatible-secret-picker.test.tsx \
  app/managed/agents/components/create-agent-dialog.test.tsx \
  app/managed/vaults/components/create-vault-dialog.test.tsx \
  app/managed/sessions/components/create-session-dialog.test.tsx
```

- Exit status: `0`.
- Result: `5/5` files and `313/313` tests passed.
- One existing React stderr warning reported the test-only `onSelectValue` property in `create-agent-dialog.test.tsx`; it was warning-only and did not affect test results.

### Complete Task 8 Backend Suite

The exact 16-file backend command from Task 8 exited `0`.

- Result: `194 passed, 0 failed` in `34.80s`.
- Warning result: `135 warnings`, all instances of the existing SQLAlchemy FK-cycle `SAWarning` from `backend/tests/conftest.py:148`.
- The count increased from the pre-fix report only because the new database-backed cases each emit that same baseline warning.

### Complete Task 8 Frontend Suite

The exact 10-file frontend command from Task 8 exited `0`.

- Result: `10/10` files and `351/351` tests passed in `1.77s`.
- No test warnings or errors were emitted.

### Static Checks

```bash
cd frontend
bun run type-check
```

- Exit status: `0`; `tsc --noEmit` produced no diagnostics.

```bash
cd frontend
bun run lint
```

- Exit status: `0`.
- Result: `692 warnings, 0 errors`; `609` warnings are potentially fixable with `--fix`.
- This exactly matches the Task 8 lint baseline. Rule messages that contain an `Error:` heading remain ESLint warnings; the summary confirms zero errors.

```bash
git diff --check
git diff --check 3f48a4e2bc8dc3a91a180f7c4c8bdd05df4d3d18..HEAD
```

- Both commands exited `0`; no whitespace errors were found in the worktree or complete fix range.

### Compatibility Boundaries

- `git diff 3f48a4e2..HEAD --name-only -- backend/alembic` was empty: no Alembic changes.
- The selector-path `secret_data` search across `use-service-credentials.ts`, `service-credential-select.tsx`, and `create-trigger-dialog.tsx` returned no matches.
- The `mcp_oauth|oauth` search in `create-credential-dialog.tsx` returned no matches; Vault creation still has no OAuth branch.
- The production/test portion of the fix range contains only the eight implementation files listed above; it changes no route decorators, API field names, entity types, or database schema files.

## Commits

- `ee7a1110f7392ff70fb1df408d3a1caff9b6a00c` — `fix(trigger): sanitize invalid webhook secret kind`
- `90585dbab25351d127d8d619b7d7b712d63fb2ba` — `fix(environment): normalize direct secret references`
- `c595544a53c2cdc8d846a787bccd410154c9fe64` — `fix(frontend): normalize active credential terminology`
- Final report commit: this report is committed separately as the final branch head and is identified in the handoff.

## Concerns

1. The backend suite still emits the pre-existing SQLAlchemy FK-cycle warning from `backend/tests/conftest.py:148`; there are no backend test failures.
2. Frontend lint still emits the pre-existing `692`-warning baseline with zero errors; this fix wave does not alter unrelated lint debt.
3. The targeted agent-dialog test emits one existing React warning about a test-only `onSelectValue` property; all targeted and full required suites pass.
4. Inactive locale catalog keys still contain legacy terms by design because no production call site renders them; changing them would violate the requested active-path-only scope.

No migration, plaintext selector access, OAuth creation branch, route/API/type rename, or unresolved finding remains.
