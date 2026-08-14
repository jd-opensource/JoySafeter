# Task 7 Report: Normalize User-Facing Credential Terminology

## Status

- **Status:** COMPLETE
- **Workspace:** `/Users/yuzhenjiang1/Downloads/workspace/JoySafeter/.worktrees/credential-domain-normalization-phase-1`
- **Branch:** `credential-domain-normalization-phase-1`
- **Base:** `0d5fcb9a02d798cd512ccc3611dee5bd16f63c17`
- **Implementation head:** `18afd5762fb8a7ead811a546992aab825f90632e`
- **Implementation commit:** `18afd5762fb8a7ead811a546992aab825f90632e` (`feat(frontend): normalize credential terminology`)
- **Push/main checkout:** Not pushed; main checkout was not modified.

## Files

- Created `frontend/lib/i18n/credential-terminology.test.ts`
- Modified `frontend/lib/i18n/locales/en.ts`
- Modified `frontend/lib/i18n/locales/zh.ts`
- Modified `frontend/app/managed/quickstart/page.tsx`
- Modified `frontend/app/managed/sessions/components/create-session-dialog.tsx`
- Created `.superpowers/sdd/2026-08-07-credential-domain-normalization-phase-1/task-7-report.md`

## TDD Evidence

### RED

The bilingual contract was created before any production edit, then run with:

```bash
cd frontend
bun run test -- lib/i18n/credential-terminology.test.ts
```

Observed result: exit 1; 1 test file failed and 2 tests failed for the intended legacy vocabulary.

- English: expected `Connections & Credentials`, received `Secrets` at `nav.secrets`.
- Chinese: expected `连接与凭据`, received `密钥` at `nav.secrets`.

### GREEN

After the minimal locale and call-site implementation, the contract was rerun:

```bash
cd frontend
bun run test -- lib/i18n/credential-terminology.test.ts
```

Observed result: exit 0; 1 test file passed and 2 tests passed.

The exact affected suite from the brief was then run:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  components/managed/triggers/create-trigger-dialog.test.tsx \
  app/managed/vaults/components/create-credential-dialog.test.tsx \
  app/managed/sessions/components/create-session-dialog.test.tsx \
  hooks/managed/use-quickstart-chat.test.tsx
```

Observed result: exit 0; 5 test files passed and 51 tests passed.

Static verification:

```bash
cd frontend
bun run type-check
```

Observed result: exit 0 (`tsc --noEmit`).

An additional runtime audit imported both locale objects and checked 62 bilingual exact-string rows, both existing `manage.apiKeys` production values, the mandated `managed.apiKeys` contract values, preserved Quickstart guidance strings, and absence of legacy Quickstart `model configuration`/`Vault` nouns. It exited 0.

## Requirement Mapping

1. **Bilingual terminology contract**
   - Added the exact contract from the brief.
   - Captured genuine RED evidence before modifying production files.

2. **Navigation and page copy**
   - Updated the specified navigation, Connections & Credentials, Model Connection, Service Credential, MCP Credential Set, Project Access Token, empty-state, archive/delete/back, and search values in English and Chinese.
   - Kept legacy internal keys such as `secrets`, `vaults`, and `apiKeys` unchanged.
   - Preserved the production `manage.apiKeys.*` call sites and pinned those values to the same required copy.

3. **Trigger and Environment copy**
   - Added every specified Trigger Service Credential/Credential Field state and `Authentication Methods` copy in both locales.
   - Updated the specified Environment labels, selectors, search/empty text, authentication method text, and related field tooltip/hint nouns.

4. **Session and Quickstart copy**
   - Updated only the specified Session MCP Credential Set values and the Chinese advanced-summary fallback literal.
   - Replaced Quickstart user-facing `model configuration` and `Vault` nouns while preserving the existing Step 1/2 `engineHint` and `secretHint` guidance structure.
   - Added `resourceKindEnvironment`, `resourceKindMcpCredentialSet`, and `resourceKindAgent`, and replaced the hard-coded editor label with the exact translated-key selection.
   - Added `t` to the `useMemo` dependency list because the memo now reads translations.

5. **Static Bearer creation copy**
   - Added the exact MCP Bearer title, description, token label/placeholder, pending label, and submit label in both locales.
   - Left optional legacy locale keys in place, but verified the production creation dialog does not reference `type`, `connect`, or `connecting`.

6. **Boundaries**
   - Did not rename routes, query parameters, API fields, TypeScript entity types, or existing production i18n call-site keys.
   - Did not modify the main checkout or push the branch.
   - Did not touch `.deps/SkillSpector`.

## Parked-Dependency Closure

- **Task 5 closed:** `CreateTriggerDialog` already referenced the parked `managed.triggers.serviceCredential*` and `managed.triggers.credentialField*` keys. Task 7 now supplies all required English and Chinese values, including unavailable, load-failed, empty, placeholder, count, and authentication-method states.
- **Task 6 closed:** `CreateCredentialDialog` already referenced the parked `managed.vaults.cred.tokenPlaceholder`, `adding`, and `add` keys. Task 7 now supplies those values and normalizes the title, description, and token label for static MCP Bearer creation.

## Concerns

- The brief mandates a `managed.apiKeys.*` terminology contract, while the existing API-token page intentionally uses `manage.apiKeys.*`. Both paths now carry identical required Task 7 copy so no existing call site was renamed; this deliberate duplication should remain synchronized in future copy changes.
- No unresolved test, type-check, scope, or parked-dependency issue remains.

## Fix Round 1

### Status

- **Finding:** Medium test-quality gap in the bilingual terminology contract.
- **Disposition:** RESOLVED.
- **Pre-fix head:** `55e150871f9a57f462c763b80c2f485b13b4d474`
- **Fix implementation head:** `855ecf5e06e247029dbb39e6b4d2e1143f8d5f1f`
- **Fix implementation commit:** `855ecf5e06e247029dbb39e6b4d2e1143f8d5f1f` (`test(frontend): expand credential terminology contract`)
- **Production files:** Unchanged in Fix Round 1.
- **Push/main checkout:** Not pushed; main checkout was not modified.

### Finding Disposition

The original contract asserted only 10 paths per locale and checked `managed.apiKeys.title` without checking the production `manage.apiKeys.*` path. The replacement contract now:

- Uses literal, table-driven English and Chinese expectations.
- Covers both mandated `managed.apiKeys.*` values and production `manage.apiKeys.*` values.
- Adds direct synchronization assertions for all relevant duplicated API-token fields.
- Restricts legacy Quickstart noun checks to the exact model-connection and MCP-credential-set paths changed by Task 7 instead of scanning the full locale catalog.

### Coverage

- **Bilingual exact-value paths:** 96 paths / 192 literal English and Chinese values.
- **Generated contract assertions:** 219 total.
- **API-token synchronization:** 6 fields in both locales: `title`, `subtitle`, `create`, `empty`, `revokeTitle`, and `revoke`.
- **Focused Quickstart legacy checks:** 21 paths: 8 Model Connection paths and 13 MCP Credential Set paths.

Exact-value categories:

- Navigation: 3 paths.
- Connections & Credentials page/search/empty/delete/back copy: 8 paths.
- Model Connection and Service Credential labels: 2 paths.
- MCP Credential Set page/search/empty/archive/delete/back copy: 10 paths.
- Project Access Token mandated/production/search copy: 13 paths.
- Trigger states and labels: 10 paths.
- Environment labels, selector states, tooltip/hint text, and validation: 14 paths.
- Session labels, search, navigation, and advanced summary: 6 paths.
- Quickstart resource kinds, model wording, preserved guidance, and MCP wording: 24 paths.
- Vault static Bearer creation copy: 6 paths.

### Mutation Evidence

After expanding the contract, `manage.apiKeys.title` was temporarily changed from `Project Access Tokens` to `Project API Tokens`, then the contract was run:

```bash
cd frontend
bun run test -- lib/i18n/credential-terminology.test.ts
```

Observed RED result: exit 1; 2 assertions failed and 217 passed.

- The exact `manage.apiKeys.title` assertion detected the wrong production value.
- The `managed.apiKeys.title` / `manage.apiKeys.title` synchronization assertion detected the drift.

The temporary mutation was restored immediately. A locale diff check confirmed no production file remained modified, and the same command returned exit 0 with 219/219 assertions passing.

### Verification

Exact affected suite:

```bash
cd frontend
bun run test -- \
  lib/i18n/credential-terminology.test.ts \
  components/managed/triggers/create-trigger-dialog.test.tsx \
  app/managed/vaults/components/create-credential-dialog.test.tsx \
  app/managed/sessions/components/create-session-dialog.test.tsx \
  hooks/managed/use-quickstart-chat.test.tsx
```

Observed result: exit 0; 5 test files passed and 268/268 tests passed.

Type-check:

```bash
cd frontend
bun run type-check
```

Observed result: exit 0 (`tsc --noEmit`).

### Commits

- `18afd5762fb8a7ead811a546992aab825f90632e` — Task 7 implementation.
- `55e150871f9a57f462c763b80c2f485b13b4d474` — Initial Task 7 report.
- `855ecf5e06e247029dbb39e6b4d2e1143f8d5f1f` — Fix Round 1 terminology-contract expansion.

### Concerns

- The duplicated `managed.apiKeys.*` and production `manage.apiKeys.*` structures remain for compatibility, but the relevant values now have both exact-value and synchronization coverage.
- No production mismatch was exposed by the expanded contract, so Fix Round 1 changes only the contract and this report.
