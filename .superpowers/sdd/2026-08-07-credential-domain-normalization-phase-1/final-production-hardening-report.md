# Credential Domain Normalization Phase 1 Final Production Hardening Report

**Status:** DONE_WITH_CONCERNS
**Verification date:** 2026-08-10
**Workspace:** `/Users/yuzhenjiang1/Downloads/workspace/JoySafeter/.worktrees/credential-domain-normalization-phase-1`
**Branch:** `credential-domain-normalization-phase-1`
**Fix base SHA:** `a33736fa75e9c7ed619c30b8c8a55bd99ffeffc9`
**Whole-branch diff base:** `c923500d`

## Finding 1: Project-Scoped MCP Credential Set Warning

### Root Cause

- The active key is `managed.vaults.sharedWarning`, rendered by `frontend/app/managed/vaults/components/create-vault-dialog.tsx`.
- Both locale values described organization-wide sharing and tied access to Project Access Tokens.
- Vault creation, reads, and mutations pass `auth_ctx.project_id`; `VaultService` filters `JoySafeterVault.project_id` for project-scoped access. Project Access Tokens are a separate API authentication concept, not the Vault permission boundary.

### RED/GREEN

- RED: the exact bilingual terminology contract and Create Vault dialog test expected current-project sharing plus project permissions. The affected frontend run failed both locale assertions and the rendered-dialog assertion.
- GREEN: both locales now state that MCP Credential Sets are shared within the current project and require appropriate project permissions. Internal keys were not renamed.
- The focused frontend GREEN run passed `6/6` files and `417/417` tests.

## Finding 2: Blank Secret Field Names

### Root Cause

- `CreateSecretRequest.data` and `UpdateSecretRequest.data` normalized selected values but never validated dictionary keys.
- PostgreSQL JSON accepted empty and whitespace-only keys. The Secret list returned raw stored key names, detail responses retained them while masking values, the frontend parser accepted them, and the Trigger dialog rendered every key as a Radix `SelectItem` value.
- Radix rejects an empty item value, so a malformed current or historical row could crash the field selector.

### Validation and Persistence Contract

- Create and update now reject only empty or whitespace-only field names.
- Nonblank field names are preserved exactly, including leading or trailing whitespace; the fix does not silently rename keys. Existing value-trimming conventions remain unchanged.
- HTTP rejection uses the existing structured request-validation contract:
  - status `422`
  - code `REQUEST_VALIDATION_ERROR`
  - `user_action="fix_input"`
  - `data.errors[0].field="body.data"`
  - message `Value error, Secret field names must not be blank`
- Create rejection persists no row. Update rejection leaves the stored encrypted data unchanged.

### Historical Compatibility and Defense in Depth

- Historical database rows remain readable and require no migration.
- Secret list metadata omits empty and whitespace-only keys.
- Secret detail and other `SecretResponse` paths omit those malformed keys before masking; no plaintext value is exposed.
- The frontend list/detail parsers independently omit malformed keys while preserving nonblank names exactly.
- `ServiceCredentialSelect` excludes malformed keys from its field count.
- The Trigger dialog independently filters malformed keys before default selection, validity checks, or `SelectItem` rendering, even when its parser is deliberately bypassed in the regression test.

### RED/GREEN

- RED backend: `3 failed, 3 warnings`; create returned `201`, update returned `200`, and historical list metadata exposed four keys instead of the two usable names.
- GREEN backend: `3 passed, 3 warnings`; both writes return structured `422` responses with no persistence, and historical list/get responses expose only usable masked metadata.
- RED frontend included parser retention of blank keys, a field count of `3` instead of `1`, and the test Radix boundary throwing on a blank item value.
- GREEN frontend is included in the `417/417` focused result and the `475/475` expanded result.

## Finding 3: Service Credential Cursor Cycles

### Root Cause

- `fetchAllServiceCredentials` compared only `page.last_id` with the immediately previous cursor.
- A non-consecutive cycle such as `A → B → A` passed that check and could continue requesting duplicate pages indefinitely.

### RED/GREEN

- RED: the three-page cycle test expected rejection after exactly `3` requests; the old implementation made a fourth request.
- GREEN: the hook tracks every seen cursor in a `Set`, rejects the cyclic third page before accumulating its payload, and makes exactly `3` requests.

## Finding 4: Runtime Presenter Inventory Source

### Root Cause

- Alert and suggestion finite families were derived by scanning keys already present in the union of both locale catalogs.
- If a runtime-produced key was removed from both catalogs, it disappeared from the expected family and the audit falsely passed.
- Production rendering uses `alertDetailKey` and `suggestionMessageKey` from `frontend/lib/managed/analytics/health-presenter.ts`. Their machine types originate from `backend/app/joysafeter_domain/services/analytics_service.py`.

### Runtime Source of Truth and Mutation Evidence

- The presenter now exports `ALERT_DETAIL_KEYS` and `SUGGESTION_MESSAGE_KEYS`, derived directly from its production type-to-slug mappings plus each unknown fallback.
- The active inventory consumes those exported runtime key families instead of catalog prefixes; no second manually drifting mapping was added.
- RED mutation evidence removed `analytics.alerts.detail.slowAgent` and `analytics.tokenSummary.suggestionMessages.highQueueWait` from both in-memory catalogs. The old audit returned no missing keys.
- GREEN mutation evidence reports both keys missing from both catalogs. The exact inventory remains deterministic at `157` source files and `1,584` active leaves.

## Finding 5: Design Whitespace

### RED/GREEN

- RED: `git diff --check c923500d..HEAD` exited `2` for trailing whitespace on design lines `3` and `4` plus a new blank line at EOF.
- GREEN: the two trailing spaces and extra EOF blank line were removed. The committed full-range command now exits `0`.

## Full Verification

### Complete Task 8 Backend Suite

The exact 16-file Task 8 command exited `0`:

- `197 passed, 0 failed` in `38.03s`.
- `138 warnings`, all the existing SQLAlchemy unresolvable-FK-cycle `SAWarning` from `backend/tests/conftest.py:148`.

### Expanded Affected Frontend Suite

The Task 8 frontend set plus Create Vault and analytics presenter coverage exited `0`:

- `12/12` files passed.
- `475/475` tests passed in `3.81s`.
- Includes terminology/inventory, the catalog-removal negative test, Secret parser/selector/dialog defenses, cursor-cycle request count, Create Vault copy, and presenter key contracts.

### Static and Compatibility Checks

- `bun run type-check`: exit `0`, no diagnostics.
- `bun run lint`: exit `0`, unchanged baseline `692 warnings, 0 errors`; `609` warnings are potentially fixable.
- `git diff --check`: exit `0`.
- `git diff --check c923500d..HEAD`: exit `0` after the implementation commits.
- No `backend/alembic` file changed in `c923500d..HEAD`.
- Selector paths contain no `secret_data` access.
- MCP Credential creation contains no `mcp_oauth` or OAuth branch.
- Changed API modules contain no route-decorator diff.
- The stale organization/Project-Access-Token warning text is absent.
- No route, API field, resource ID, query parameter, internal entity type, or database schema was renamed.

## Commits

- `6a8896bf3eafa5f15c3afcb364a4ad101b3320af` — `fix(secret): harden credential field boundaries`
- `0ca51c4757a06906f3284d12d263075fa7f05dd7` — `fix(frontend): close normalization review gaps`
- This report is committed separately and its SHA is recorded in the final handoff.

## Concerns

1. The complete backend suite retains `138` pre-existing SQLAlchemy FK-cycle warnings; there are no backend failures.
2. Frontend lint retains the established `692`-warning baseline with zero errors; this wave adds no warning.

All `2 Important` and `3 Minor` findings are addressed. No migration, plaintext exposure, OAuth expansion, route/API/type rename, amend, push, or main-checkout change was performed.
