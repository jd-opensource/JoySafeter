# Management Context API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow organization and project administration without implicitly changing the user's active working context.

**Architecture:** All management reads and mutations identify their target organization or project in the route. Context switching remains a separate explicit user action used by runtime/resource pages, not by settings pages.

**Tech Stack:** FastAPI, Next.js App Router, TanStack Query, Zustand, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-21-organization-project-governance-design.md`

## Global Constraints

- Opening a management route must not call `switchProject` or `switch-context`.
- Every mutation authorizes against its route target.
- Existing active-context endpoints remain temporarily compatible while the UI migrates.
- Do not commit changes unless the user explicitly requests a commit.

---

### Task 1: Add Project-Scoped Token Endpoints

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Test: `backend/tests/test_project_admin_dependency_contract.py`

- [ ] Write failing list/create/revoke target-project tests.
- [ ] Run tests and confirm expected failures.
- [ ] Add `/projects/{project_id}/api-keys` routes.
- [ ] Authorize all token actions against the path project.
- [ ] Keep old endpoints as compatibility delegates.
- [ ] Run focused tests and confirm pass.

### Task 2: Decouple Project Settings Shell

**Files:**
- Modify: `frontend/components/managed/projects/project-settings-shell.tsx`
- Modify: `frontend/app/managed/api-keys/page.tsx`
- Modify: `frontend/app/managed/projects/[projectId]/tokens/page.tsx`
- Test: `frontend/components/managed/projects/project-settings-shell.test.tsx`

- [ ] Write failing test proving settings navigation does not switch context.
- [ ] Run test and confirm failure.
- [ ] Load project and organization identity by route scope.
- [ ] Update token requests to path-scoped endpoints.
- [ ] Run focused tests and confirm pass.

### Task 3: Add Explicit Context Actions

**Files:**
- Modify: `frontend/app/managed/projects/page.tsx`
- Modify: `frontend/app/managed/settings/page.tsx`
- Test: `frontend/app/managed/projects/page.test.tsx`
- Create or modify: organization page interaction tests.

- [ ] Write failing tests for separate Manage and Use/Switch actions.
- [ ] Run tests and confirm failure.
- [ ] Add explicit project and organization context buttons.
- [ ] Confirm Manage does not mutate global context.
- [ ] Run focused tests and confirm pass.

### Task 4: Validate Context Isolation

- [ ] Run project store/provider tests.
- [ ] Run affected frontend tests.
- [ ] Run TypeScript and ESLint checks.
- [ ] Run `git diff --check`.
