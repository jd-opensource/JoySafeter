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
