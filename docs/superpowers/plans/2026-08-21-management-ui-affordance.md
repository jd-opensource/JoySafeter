# Management UI Affordance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make organization and project management actions visible, predictable, accessible, and consistent across desktop and mobile layouts.

**Architecture:** Introduce reusable resource-list action patterns, keep primary navigation visible, move destructive operations into detail lifecycle pages, and show effective permission plus its source wherever users make access decisions.

**Tech Stack:** Next.js 16, React 19, TanStack Query/Table, shadcn/Radix UI, Tailwind CSS, Vitest and Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-21-organization-project-governance-design.md`

## Global Constraints

- Reuse existing shadcn components and visual tokens.
- Do not redesign the visual theme.
- Do not rely on whole-row click as the only navigation affordance.
- Never render an empty action column.
- Do not commit changes unless the user explicitly requests a commit.

---

### Task 1: Improve Shared Resource Table Actions

**Files:**
- Modify: `frontend/components/managed/shared/data-table.tsx`
- Modify: `frontend/components/managed/shared/action-menu.tsx`
- Test: `frontend/components/managed/shared/data-table.test.tsx`

- [ ] Write failing tests for explicit action labels and empty-menu omission.
- [ ] Run tests and confirm failure.
- [ ] Preserve table semantics and visible keyboard focus.
- [ ] Require accessible labels for icon-only menus.
- [ ] Render action column only when at least one row has actions.
- [ ] Run focused tests and confirm pass.

### Task 2: Redesign Project List Affordance

**Files:**
- Modify: `frontend/app/managed/projects/page.tsx`
- Test: `frontend/app/managed/projects/page.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] Write failing tests for visible Manage/View and Use Project actions.
- [ ] Run tests and confirm failure.
- [ ] Make project name an explicit link.
- [ ] Add effective permission and current/default state columns.
- [ ] Remove list-level archive shortcut.
- [ ] Add responsive project cards for narrow screens.
- [ ] Run focused tests and confirm pass.

### Task 3: Redesign Organization List Affordance

**Files:**
- Modify: `frontend/app/managed/settings/page.tsx`
- Create: `frontend/app/managed/settings/page.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] Write failing tests for separate Manage and Switch actions.
- [ ] Run tests and confirm failure.
- [ ] Add explicit actions and current-context labels.
- [ ] Move destructive actions out of the list.
- [ ] Add responsive organization cards.
- [ ] Run focused tests and confirm pass.

### Task 4: Clarify Permission Sources

**Files:**
- Modify: `frontend/components/managed/projects/project-access-page.tsx`
- Modify: `frontend/app/managed/members/page.tsx`
- Modify: `frontend/lib/managed/project-access.ts`
- Test: `frontend/components/managed/projects/project-access-page.test.tsx`
- Test: `frontend/lib/managed/project-access.test.ts`

- [ ] Write failing tests for inherited, Default, and explicit sources.
- [ ] Run tests and confirm failure.
- [ ] Render effective role and source separately.
- [ ] Add role-change impact summaries.
- [ ] Run focused tests and confirm pass.

### Task 5: Align Project Detail Controls

**Files:**
- Modify: `frontend/components/managed/projects/project-overview-page.tsx`
- Modify: `frontend/components/managed/projects/project-lifecycle-page.tsx`
- Modify: `frontend/app/managed/api-keys/page.tsx`
- Test: corresponding component tests.

- [ ] Write failing capability-gating tests.
- [ ] Run tests and confirm failure.
- [ ] Gate controls on operation-specific capabilities.
- [ ] Explain disabled states inline.
- [ ] Make Slug an impact-confirmed advanced action.
- [ ] Keep destructive operations only in Lifecycle.
- [ ] Run focused tests and confirm pass.

### Task 6: Final UI Validation

- [ ] Run all affected Vitest suites.
- [ ] Run frontend type-check and ESLint.
- [ ] Run Prettier check.
- [ ] Run production build.
- [ ] Record Browser plugin absence or run rendered desktop/mobile QA.
- [ ] Run `git diff --check`.
