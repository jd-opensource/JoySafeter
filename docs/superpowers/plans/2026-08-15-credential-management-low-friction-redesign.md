# Credential Management Low-Friction Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the credential management tabs around one low-friction resource panel with a single contextual create action, progressive filters, name-first identity, responsive cards, and preserved lifecycle/deep-link behavior.

**Architecture:** Add credential-module composition components instead of changing the global managed `DataTable`/`FilterBar` APIs. The shell owns tab routing and the single create action; each list owns data/lifecycle behavior and feeds a shared `CredentialListPanel` plus `CredentialIdentity` presentation.

**Tech Stack:** Next.js 16, React 19, TypeScript, TanStack Query/Table, Radix dropdown menu, existing shadcn components, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-15-credential-management-low-friction-redesign.md`

## Global Constraints

- Preserve `/managed/credentials` canonical routes and all `create=*` deep links.
- Preserve server-side kind filtering, cursor pagination, independent tab state, and stale-scope guards.
- Preserve every lifecycle capability covered by `credential-parity.test.tsx`.
- Use one visible create action per writable tab and none in read-only mode.
- Do not change backend APIs or add UI dependencies.
- Do not commit or push unless explicitly requested.

---

### Task 1: Shared Credential Resource Panel

**Files:**

- Create: `frontend/components/managed/credentials/credential-list-panel.tsx`
- Create: `frontend/components/managed/credentials/credential-identity.tsx`
- Test: `frontend/components/managed/credentials/credential-list-panel.test.tsx`

**Interfaces:**

- Produces `CredentialListPanel<T>` for toolbar, filters, empty states, desktop table, mobile cards, and pagination.
- Produces `CredentialIdentity` for name-first identity, public ID copy, subtitle, and badges.

- [ ] Write failing tests for collapsed filters, active filter chips, clear behavior, one primary action, mobile card rendering, and nested event isolation.
- [ ] Run the focused tests and verify they fail.
- [ ] Implement the minimal shared components using existing UI primitives.
- [ ] Run the focused tests and verify they pass.

### Task 2: Single Contextual Create Flow

**Files:**

- Modify: `frontend/components/managed/credentials/credential-management-shell.tsx`
- Modify: `frontend/app/managed/credentials/page.tsx`
- Test: `frontend/components/managed/credentials/credential-management-shell.test.tsx`
- Test: `frontend/components/managed/credentials/credential-parity.test.tsx`

**Interfaces:**

- Consumes existing `openForKind(kind)` and deep-link consumption.
- Produces tab-specific create labels/actions passed into each list panel.

- [ ] Update tests to require one tab-specific create action and no generic page action.
- [ ] Run focused shell/parity tests and verify the expected failures.
- [ ] Move creation ownership to the shell/list panel boundary without changing dialogs or deep links.
- [ ] Run focused shell/parity tests and verify they pass.

### Task 3: Model Connection List Migration

**Files:**

- Modify: `frontend/components/managed/credentials/model-connection-list.tsx`
- Test: `frontend/components/managed/credentials/model-connection-list.test.tsx`

**Interfaces:**

- Consumes `CredentialListPanel` and `CredentialIdentity`.
- Preserves model catalog compatibility labels, default actions, archive/restore/delete, and detail navigation.

- [ ] Add failing assertions for name-first identity, compact filters, empty/search states, and mobile model cards.
- [ ] Run the focused test and verify failure.
- [ ] Migrate model rendering and pagination to the shared panel.
- [ ] Run the focused test and verify pass.

### Task 4: Service and MCP List Migration

**Files:**

- Modify: `frontend/components/managed/credentials/service-credential-list.tsx`
- Modify: `frontend/components/managed/credentials/mcp-vault-list.tsx`
- Test: `frontend/components/managed/credentials/service-credential-list.test.tsx`
- Test: `frontend/components/managed/credentials/mcp-vault-list.test.tsx`

**Interfaces:**

- Consumes the same panel/identity interfaces as the model list.
- Preserves independent API dependencies, lifecycle guards, and MCP detail navigation.

- [ ] Add failing service/MCP assertions for unified toolbar, identity hierarchy, empty states, and mobile cards.
- [ ] Run the focused tests and verify failure.
- [ ] Migrate both lists without adding model-catalog dependencies.
- [ ] Run focused and parity tests and verify pass.

### Task 5: Copy, Accessibility, and Terminology

**Files:**

- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/lib/i18n/credential-terminology.test.ts`
- Test: credential component tests above.

**Interfaces:**

- Produces concise labels, filter copy, purpose-specific empty states, and accessible control labels.

- [ ] Add failing terminology assertions for the new labels and descriptions.
- [ ] Run the terminology test and verify failure.
- [ ] Add English/Chinese copy and accessibility labels.
- [ ] Run terminology and credential component tests and verify pass.

### Task 6: Full Validation and Browser QA

**Files:**

- Modify only if validation reveals implementation defects.

**Interfaces:**

- Verifies the completed page as a coherent user flow.

- [ ] Run credential tests, full Vitest, TypeScript, ESLint, and production build.
- [ ] Start the local frontend with representative credential data or existing mocked backend support.
- [ ] Use Playwright because no Browser plugin is available in this session.
- [ ] Verify models, services, MCP, filter interaction, one create action, empty state, keyboard row navigation, and mobile layout.
- [ ] Capture desktop and mobile screenshots outside the repository and inspect them with `view_image`.
- [ ] Remove temporary QA artifacts and report remaining risk.
