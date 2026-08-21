# Organization And Project Context Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ambiguous `Default / Default` contexts with recognizable names, explicit ownership metadata, and a low-cognitive-load organization/project switcher.

**Architecture:** Centralize initial organization/project creation in `OrganizationService`, enrich organization responses with owner identity, and make the sidebar render stable hierarchical context. A data migration repairs records created by the legacy bootstrap signature without changing permission semantics.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Next.js, React, TanStack Query, Vitest, Testing Library

**Spec:** `docs/superpowers/specs/2026-08-21-context-identity-design.md`

## Global Constraints

- `is_default` is lifecycle state, not a display name.
- Names remain editable and need not be globally unique.
- Organization/project authorization behavior must not change.
- Legacy `Default / Default` routes or compatibility aliases must not be introduced.

---

### Task 1: Centralize Initial Identity Creation

**Files:**

- Modify: `backend/app/joysafeter_domain/services/joysafeter_organization_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_auth_service.py`
- Test: `backend/tests/test_auth_bootstrap_project_member.py`
- Test: `backend/tests/test_organization_member_error_contract.py`

- [x] Add failing tests for personalized bootstrap names and `Main/main` projects.
- [x] Add an uncommitted service creation path for authentication transactions.
- [x] Remove duplicated organization/project construction from authentication.
- [x] Run focused backend tests.

### Task 2: Expose Organization Ownership Context

**Files:**

- Modify: `backend/app/joysafeter_api/api/v1/organizations.py`
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Test: `backend/tests/test_organization_member_error_contract.py`

- [x] Add failing response-contract tests for owner identity.
- [x] Query owner metadata without per-row queries.
- [x] Return consistent owner fields from organization list and auth context.
- [x] Run focused API tests.

### Task 3: Clarify Organization And Project Switching

**Files:**

- Modify: `frontend/stores/managed/project-store.ts`
- Modify: `frontend/providers/project-provider.tsx`
- Modify: `frontend/components/app-sidebar/app-sidebar.tsx`
- Modify: `frontend/lib/i18n/locales/en.ts`
- Modify: `frontend/lib/i18n/locales/zh.ts`
- Test: `frontend/components/app-sidebar/app-sidebar.test.tsx`

- [x] Add failing tests for hierarchy, grouping, role labels, and default badges.
- [x] Extend frontend organization types with owner identity.
- [x] Replace position-based colors with stable ID-derived colors.
- [x] Render full two-line current context and grouped switch options.
- [x] Expand search to owner and slug metadata.
- [x] Run focused frontend tests.

### Task 4: Repair Legacy Generated Names

**Files:**

- Create: `backend/alembic/versions/20260821_000002_context_identity.py`

- [x] Add a forward-only data migration for the exact legacy signatures.
- [x] Preserve custom names and unrelated default-project records.
- [x] Validate the migration graph and SQL formatting.

### Task 5: Full Verification

**Files:**

- Verify all modified files.

- [x] Run backend lint and focused tests.
- [x] Run frontend type-check and focused tests.
- [x] Run complete frontend tests and production build.
- [x] Run `git diff --check` and audit legacy literals.
