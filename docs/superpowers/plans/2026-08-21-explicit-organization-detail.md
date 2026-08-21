# Explicit Organization Detail Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every organization-management and member action visibly and technically scoped to the organization selected from the organization list.

**Architecture:** Keep `/managed/settings` as a collection page and introduce an organization detail shell at `/managed/settings/organizations/[organizationId]`. Move overview, member management, and lifecycle actions into that shell, and expose only organization-ID-scoped backend member APIs.

**Tech Stack:** FastAPI, SQLAlchemy, Next.js 16 App Router, React 19, TanStack Query, shadcn/Radix UI, Tailwind CSS, Vitest, Testing Library, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-organization-project-governance-design.md`

## Global Constraints

- Reuse the existing visual system; do not introduce a new theme.
- `Switch` changes active working context; `Manage` and `View` never switch context.
- Every member operation carries an explicit organization ID.
- Owner transfer remains an owner-only lifecycle operation.
- Remove obsolete implicit member routes rather than retaining redirects or aliases.
- Preserve unrelated `.deps/SkillSpector` changes.
- Do not commit unless explicitly requested.

---

### Task 1: Add Explicit Organization Member APIs

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/organizations.py`
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Modify: `backend/tests/test_organization_member_error_contract.py`
- Modify: `backend/tests/test_read_route_dependency_contract.py`

- [ ] Write failing route-contract tests for explicit member list, candidate search, add, update, and remove endpoints.
- [ ] Verify the tests fail because explicit endpoints are incomplete.
- [ ] Add paginated organization member responses and explicit candidate search.
- [ ] Add email-based member creation, role update, and removal under `/organizations/{organization_id}`.
- [ ] Remove implicit `/auth/members` and `/auth/search-users` routes.
- [ ] Run focused backend contract and lifecycle tests.

### Task 2: Create Organization Detail Shell

**Files:**
- Create: `frontend/app/managed/settings/organizations/[organizationId]/layout.tsx`
- Create: `frontend/components/managed/settings/organization-detail-shell.tsx`
- Create: `frontend/components/managed/settings/organization-detail-shell.test.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`

- [ ] Write failing tests for organization identity, back navigation, current state, role, and scoped tabs.
- [ ] Verify tests fail before implementation.
- [ ] Fetch the organization by route ID without switching active context.
- [ ] Render Overview & Settings and Members & Roles tabs with the same organization ID.
- [ ] Show read-only context for ordinary members.
- [ ] Run focused shell tests.

### Task 3: Simplify Organization Collection Page

**Files:**
- Modify: `frontend/app/managed/settings/layout.tsx`
- Modify: `frontend/app/managed/settings/page.tsx`
- Modify: `frontend/app/managed/settings/page.test.tsx`
- Delete: `frontend/components/managed/settings/organization-settings-tabs.tsx`
- Delete: `frontend/components/managed/settings/organization-settings-tabs.test.tsx`

- [ ] Write failing tests proving the collection page has no organization-scoped tabs or edit dialog.
- [ ] Verify tests fail before implementation.
- [ ] Route Manage/View to the selected organization detail.
- [ ] Keep Switch as a separate active-context action.
- [ ] Remove transfer, delete, and edit state from the collection page.
- [ ] Run focused organization-list tests.

### Task 4: Move Overview and Lifecycle Actions

**Files:**
- Create: `frontend/app/managed/settings/organizations/[organizationId]/page.tsx`
- Create: `frontend/app/managed/settings/organizations/[organizationId]/page.test.tsx`
- Modify: `frontend/lib/managed/errors.ts`

- [ ] Write failing tests for scoped edit, ownership transfer, delete, and read-only behavior.
- [ ] Verify tests fail before implementation.
- [ ] Move organization name and project-creation policy editing to the detail page.
- [ ] Keep transfer and delete in an owner-only advanced section.
- [ ] Never mutate the active organization merely by opening this page.
- [ ] Run focused overview tests.

### Task 5: Migrate Members and Project Links

**Files:**
- Move: `frontend/app/managed/settings/members/page.tsx` to `frontend/app/managed/settings/organizations/[organizationId]/members/page.tsx`
- Move: corresponding member tests
- Modify: `frontend/components/managed/projects/project-access-page.tsx`
- Modify: corresponding tests

- [ ] Write failing tests for route-ID-scoped member queries and mutations.
- [ ] Verify tests fail before implementation.
- [ ] Replace active-context member APIs with explicit organization endpoints.
- [ ] Keep owner and self-management protections visible.
- [ ] Point project access back to the current project's organization member page.
- [ ] Remove `/managed/settings/members`.
- [ ] Run focused member and project-access tests.

### Task 6: Validate Routes and Interaction

- [ ] Run backend member and route contract suites.
- [ ] Run frontend type-check and full Vitest suite.
- [ ] Run Ruff and Prettier checks.
- [ ] Run the production build and inspect generated routes.
- [ ] Verify desktop and mobile organization detail/member flows with Playwright.
- [ ] Confirm removed routes return 404 and run `git diff --check`.
