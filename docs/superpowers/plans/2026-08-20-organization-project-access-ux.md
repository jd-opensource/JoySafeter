# Organization and Project Access UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make organization membership and project access understandable and permission-consistent across the management UI.

**Architecture:** Preserve the existing two-layer backend authorization model while changing the frontend vocabulary from “project members” to “project access.” Enrich project API responses with caller-specific capability so organization management actions and project-access actions can be gated independently.

**Tech Stack:** FastAPI, SQLAlchemy async, Next.js 16, React 19, TypeScript, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-organization-project-access-ux-design.md`

## Global Constraints

- Keep Organization as the top-level user-facing term; do not introduce Workspace.
- Do not rename database tables, API paths, audit event identifiers, or backend model classes.
- User-facing project authorization is called Project Access, not Project Membership.
- Organization and project role labels must always include their scope in management UI.
- Organization invitation defaults to the valid least-privilege `member` role; legacy `developer` is forbidden.
- Project access defaults and fallbacks remain least-privilege Viewer.
- Do not overwrite unrelated existing changes in the working tree.

---

### Task 1: Lock Terminology and Access Semantics

**Files:**
- Create: `frontend/lib/i18n/organization-project-access-terminology.test.ts`
- Create: `frontend/lib/managed/project-access.test.ts`
- Create: `frontend/lib/managed/project-access.ts`
- Modify: `frontend/lib/managed/roles.ts`

**Interfaces:**
- Produces: `effectiveProjectAccessValue(access, projectRole)` and `canManageProjectAccess(capability)`.

- [ ] Write failing translation tests for scoped organization roles and Project Access terminology.
- [ ] Write failing unit tests for Viewer fallback and project-admin authorization.
- [ ] Run focused Vitest tests and confirm failures.
- [ ] Implement the minimal shared helpers and scoped role labels.
- [ ] Run focused Vitest tests and confirm passes.

### Task 2: Enrich Project Capability Responses

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Modify: `backend/tests/test_organization_member_error_contract.py`
- Modify: `backend/tests/test_me_capability.py`

**Interfaces:**
- Produces: `ProjectResponse.capability: str` and `ProjectResponse.project_role: str | None`.

- [ ] Add failing route tests for member Viewer/Editor/Admin capabilities and org-admin inheritance.
- [ ] Run focused pytest tests and confirm failures.
- [ ] Enrich list/detail/create/update project responses from organization and project roles.
- [ ] Run focused pytest tests and confirm passes.

### Task 3: Clarify Organization Members UI

**Files:**
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Modify: `frontend/app/managed/members/page.tsx`
- Modify: `frontend/components/app-sidebar/app-sidebar.tsx`

**Interfaces:**
- Consumes: scoped `roleLabel` output.

- [ ] Update failing terminology expectations for organization navigation and role copy.
- [ ] Rename generic member surfaces to Organization Members.
- [ ] Explain invitation, default-project Viewer access, and organization-wide inheritance.
- [ ] Run focused terminology and sidebar tests.

### Task 4: Replace Project Members with Project Access

**Files:**
- Modify: `frontend/app/managed/projects/[projectId]/members/page.tsx`
- Modify: `frontend/app/managed/projects/page.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

**Interfaces:**
- Consumes: `effectiveProjectAccessValue` and `canManageProjectAccess`.

- [ ] Rename page, actions, columns, empty states, and confirmations to Project Access.
- [ ] Show organization inheritance and default-project rules explicitly.
- [ ] Split project-list actions between organization admins and effective project admins.
- [ ] Replace the incorrect Editor fallback with Viewer.
- [ ] Run focused frontend tests and type-check.

### Task 5: Deep Consistency Verification

**Files:**
- Modify only if a failing consistency check identifies a directly related defect.

**Interfaces:**
- Verifies all interfaces introduced above.

- [ ] Search active frontend copy for ambiguous project-member terminology.
- [ ] Run focused frontend and backend test suites.
- [ ] Run frontend type-check and lint on changed files where supported.
- [ ] Inspect final diffs for unrelated changes and permission regressions.
- [ ] Record remaining risks and any intentionally internal `member` terminology.
