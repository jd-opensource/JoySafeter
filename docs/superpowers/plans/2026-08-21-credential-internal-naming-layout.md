# Credential Internal Naming and Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Normalize internal credential naming and dependency direction while preserving compatibility routes and stored formats.

**Architecture:** Move reusable credential UI into the canonical component package first, then rename internal symbols and parser/hook modules. Keep redirect routes and compatibility inputs at the boundary; defer backend repository decomposition to a separate backend-only phase.

**Tech Stack:** React 19, Next.js 16, TypeScript, TanStack Query, Vitest, ESLint, Python import-architecture tests.

**Spec:** `docs/superpowers/specs/2026-08-21-credential-internal-naming-layout-design.md`

## Global Constraints

- Execute only after the runtime freshness and lifecycle UX plan passes.
- Preserve `/managed/secrets`, `/managed/vaults`, `create=vault`, and v1 stored aliases.
- Do not rename Kubernetes Secret resources or historical migration/docs artifacts.
- Do not combine this work with backend repository decomposition.
- Move tests with implementation and keep each rename behavior-neutral.
- Do not commit unless explicitly requested.

---

### Task 1: Establish Naming and Import Guards

**Files:**
- Modify: `frontend/lib/i18n/credential-terminology.test.ts`
- Create: `frontend/components/managed/credentials/credential-layout-architecture.test.ts`

**Interfaces:**
- Produces: allowlists for retained compatibility routes and forbidden route-owned component imports.

- [ ] Add a failing test rejecting imports from `@/app/managed/secrets/components` and `@/app/managed/vaults/components` outside those routes.
- [ ] Add a failing inventory test for internal `mcp-vault`, `secret-response-parser`, and `vault-response-parser` filenames.
- [ ] Explicitly allow redirect routes, deployment Secret terminology, and historical docs.
- [ ] Run the two architecture tests and verify expected failures.

### Task 2: Move Credential Creation Dialogs

**Files:**
- Create: `frontend/components/managed/credentials/create-standalone-credential-dialog.tsx`
- Create: `frontend/components/managed/credentials/create-credential-group-dialog.tsx`
- Create: `frontend/components/managed/credentials/create-mcp-member-dialog.tsx`
- Move corresponding tests from `frontend/app/managed/secrets/components/` and `frontend/app/managed/vaults/components/`.
- Modify: `frontend/components/managed/credentials/credential-management-shell.tsx`
- Modify: `frontend/components/managed/credentials/mcp-credential-group-detail.tsx`

**Interfaces:**
- Produces: `CreateStandaloneCredentialDialog`, `CreateCredentialGroupDialog`, and `CreateMcpMemberDialog` from the canonical credential component package.

- [ ] Move implementations and tests without changing request payloads or behavior.
- [ ] Update imports and test mocks to canonical component paths.
- [ ] Delete obsolete route-owned component files after all consumers move.
- [ ] Run dialog, shell, parity, and scope-guard tests.

### Task 3: Rename MCP Group Components

**Files:**
- Move: `frontend/components/managed/credentials/mcp-vault-list.tsx` → `frontend/components/managed/credentials/mcp-credential-group-list.tsx`
- Move: `frontend/components/managed/credentials/mcp-vault-detail.tsx` → `frontend/components/managed/credentials/mcp-credential-group-detail.tsx`
- Move corresponding test files.
- Modify: `frontend/app/managed/credentials/mcp/[credentialGroupId]/page.tsx`
- Modify: `frontend/components/managed/credentials/credential-management-shell.tsx`

**Interfaces:**
- Produces: `McpCredentialGroupList` and `McpCredentialGroupDetail` under matching filenames.

- [ ] Move files and update all imports without altering rendered behavior.
- [ ] Update snapshots/source-contract tests to canonical paths.
- [ ] Verify `/managed/vaults` continues redirecting to the canonical MCP tab.
- [ ] Run MCP lifecycle, parity, redirect, and full frontend tests.

### Task 4: Rename Parser and Hook Modules

**Files:**
- Move: `frontend/lib/managed/secret-response-parsers.ts` → `frontend/lib/managed/credential-response-parsers.ts`
- Consolidate: `frontend/lib/managed/vault-response-parsers.ts` into `frontend/lib/managed/credential-group-response-parsers.ts`
- Move: `frontend/hooks/managed/use-compatible-secrets.ts` → `frontend/hooks/managed/use-compatible-credentials.ts`
- Modify all frontend imports and matching tests.

**Interfaces:**
- Produces: canonical parser and hook module names; parsed wire shapes remain unchanged.

- [ ] Add import-contract failures for old internal module paths.
- [ ] Move implementations and update exported symbol names where they are internal-only.
- [ ] Keep temporary re-exports only when a route or plugin imports the old path externally.
- [ ] Remove temporary re-exports once repository-wide search reports no internal consumers.
- [ ] Run parser, hook, quickstart, credential detail, and type-check suites.

### Task 5: Normalize Credential-Facing Translation Namespaces

**Files:**
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify credential UI consumers and `frontend/lib/i18n/credential-terminology.test.ts`.

**Interfaces:**
- Produces: canonical `managed.credentials.*` keys for model connections, service credentials, credential groups, and MCP members.

- [ ] Inventory every live `managed.secrets.*` and `managed.vaults.*` key and classify compatibility-only exceptions.
- [ ] Add failing paired-locale tests for the canonical replacement keys.
- [ ] Update consumers in bounded groups while keeping English and Chinese catalogs synchronized.
- [ ] Remove unused legacy keys only after source search confirms zero runtime consumers.
- [ ] Run terminology, full Vitest, TypeScript, ESLint, and production build.

### Task 6: Final Boundary Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-08-21-credential-internal-naming-layout-design.md`
- Modify: `docs/superpowers/plans/2026-08-21-credential-internal-naming-layout.md`

**Interfaces:**
- Consumes: all naming/layout tasks.
- Produces: evidence that compatibility remains only at external boundaries.

- [ ] Confirm redirect-only route directories contain no reusable implementation.
- [ ] Confirm shared credential components do not import from route directories.
- [ ] Confirm no internal imports use removed secret/vault parser, hook, or MCP component paths.
- [ ] Run full frontend tests, type checking, ESLint, build, and `git diff --check`.
- [ ] Confirm pre-existing user changes remain untouched.
