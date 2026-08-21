# Management Information Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce management-navigation cognitive load and provide coherent organization/project settings interactions.

**Architecture:** Keep the sidebar object-oriented with Organizations and Projects only. Add route-driven organization and project settings shells, move project-specific actions into project detail tabs, and fix target-project authorization at the API boundary.

**Tech Stack:** FastAPI, SQLAlchemy async, Next.js 16 App Router, React 19, TanStack Query, Zustand, shadcn/ui, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-management-information-architecture-design.md`

## Global Constraints

- Reuse the existing visual system and shared components; no visual theme rewrite.
- Sidebar Management contains only Organizations and Projects.
- Existing deep links remain compatible.
- Project route authorization uses the target project ID.
- Project-specific pages do not render until managed context matches the route project.
- Do not overwrite unrelated working-tree changes.

---

### Task 1: Enforce Target-Project Administration

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Modify: `backend/tests/test_project_member_management.py`

**Interfaces:**
- Produces: target-project admin authorization shared by list/grant/revoke access routes.

- [ ] Write failing tests proving Project Admin A cannot manage project B.
- [ ] Run focused pytest and confirm failure.
- [ ] Implement target-project capability validation.
- [ ] Run focused pytest and confirm pass.

### Task 2: Simplify Management Navigation

**Files:**
- Modify: `frontend/components/app-sidebar/app-sidebar.tsx`
- Modify: `frontend/components/app-sidebar/app-sidebar.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Create: `frontend/app/managed/settings/layout.tsx`
- Create: `frontend/components/managed/settings/organization-settings-tabs.tsx`

**Interfaces:**
- Produces: sidebar Organizations/Projects entries and organization route tabs.

- [ ] Write failing sidebar and tab tests.
- [ ] Remove Members and Access Tokens from sidebar.
- [ ] Add Manage Organizations action to the scope switcher.
- [ ] Add Organizations and Members & Roles tabs.
- [ ] Run focused frontend tests.

### Task 3: Add Scope-Aware Project Settings Shell

**Files:**
- Create: `frontend/app/managed/projects/[projectId]/layout.tsx`
- Create: `frontend/components/managed/projects/project-settings-shell.tsx`
- Create: `frontend/components/managed/projects/project-settings-shell.test.tsx`
- Create: `frontend/app/managed/projects/[projectId]/page.tsx`
- Create: `frontend/app/managed/projects/[projectId]/access/page.tsx`
- Create: `frontend/app/managed/projects/[projectId]/tokens/page.tsx`
- Create: `frontend/app/managed/projects/[projectId]/lifecycle/page.tsx`
- Modify: `frontend/app/managed/projects/[projectId]/members/page.tsx`

**Interfaces:**
- Produces: route project context synchronization and Overview/Access/Tokens/Lifecycle navigation.

- [ ] Write failing shell context and tab tests.
- [ ] Implement context synchronization and loading/error states.
- [ ] Add route pages and legacy redirect.
- [ ] Run focused shell and context tests.

### Task 4: Make Project Index Task-Oriented

**Files:**
- Modify: `frontend/app/managed/projects/page.tsx`
- Create: `frontend/app/managed/projects/page.test.tsx`

**Interfaces:**
- Consumes: project settings routes.

- [ ] Write failing tests for row navigation and simplified actions.
- [ ] Make project rows open Overview.
- [ ] Simplify project creation to name-first slug generation.
- [ ] Reduce overflow actions to Archive/Restore.
- [ ] Run focused tests.

### Task 5: Improve Project Access Feedback

**Files:**
- Create: `frontend/components/managed/projects/project-access-page.tsx`
- Modify: `frontend/app/managed/projects/[projectId]/access/page.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Create: `frontend/components/managed/projects/project-access-page.test.tsx`

**Interfaces:**
- Produces: row-level saving/saved state and explicit default-project restriction copy.

- [ ] Move the existing access implementation into a reusable component.
- [ ] Add failing interaction tests.
- [ ] Add pending/saved row feedback and disabled-state reasons.
- [ ] Run focused access tests.

### Task 6: Add Overview and Lifecycle Interactions

**Files:**
- Create: `frontend/components/managed/projects/project-overview-page.tsx`
- Create: `frontend/components/managed/projects/project-lifecycle-page.tsx`
- Create: `frontend/components/managed/projects/project-lifecycle-page.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

**Interfaces:**
- Produces: explicit project editing and lifecycle controls.

- [ ] Add Overview editing with pending/error handling.
- [ ] Add Lifecycle controls and typed archive confirmation.
- [ ] Add interaction tests for archive gating.
- [ ] Run focused tests.

### Task 7: Improve Token Completion Flow

**Files:**
- Modify: `frontend/app/managed/api-keys/page.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

**Interfaces:**
- Consumes: project settings shell context.

- [ ] Rename dismissal to explicit saved confirmation.
- [ ] Include token name in revoke confirmation.
- [ ] Verify copy feedback and current-project context.

### Task 8: Verify the Complete Management Journey

**Files:**
- Modify only for directly related defects discovered by verification.

**Interfaces:**
- Verifies all preceding interfaces.

- [ ] Run focused frontend and backend tests.
- [ ] Run frontend lint, type-check, and production build.
- [ ] Run backend Ruff checks.
- [ ] Scan sidebar and active copy for removed standalone entries.
- [ ] Attempt rendered validation with Browser or Playwright and record limitations.
- [ ] Review final diff for unrelated changes.
