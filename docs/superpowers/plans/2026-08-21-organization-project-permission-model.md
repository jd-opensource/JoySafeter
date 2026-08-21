# Organization Project Permission Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make project creation, creator authority, Default access, role transitions, and privileged project operations follow one server-authoritative capability model.

**Architecture:** Add explicit organization creation policy and project creator provenance, derive Default Viewer access instead of storing baseline rows, and authorize each operation against its real capability. Organization-level governance remains separate from project-level administration.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-21-organization-project-governance-design.md`

## Global Constraints

- Default project is renameable and cannot be archived directly.
- Creator identity is audit data, not a permanent authorization bypass.
- Organization owner/admin direct project grants must not become hidden privileges after demotion.
- Do not commit changes unless the user explicitly requests a commit.

---

### Task 1: Model Creation Policy and Provenance

**Files:**
- Modify: `backend/app/joysafeter_domain/models/joysafeter_organization.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_project.py`
- Create: `backend/alembic/versions/20260821_000001_project_governance.py`
- Test: `backend/tests/test_organization_member_error_contract.py`

**Interfaces:**
- Produces: `Organization.project_creation_policy: str`
- Produces: `Project.created_by_user_id: str | None`

- [ ] Write failing model/default tests.
- [ ] Run focused tests and confirm failure.
- [ ] Add model columns and migration.
- [ ] Run focused tests and confirm pass.

### Task 2: Derive Default Viewer Access

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_project_service.py`
- Modify: `backend/app/joysafeter_shared/common/joysafeter_auth/dependencies.py`
- Test: `backend/tests/test_project_member_management.py`
- Test: `backend/tests/test_project_lifecycle_active_tasks.py`

**Interfaces:**
- Produces: effective access that accepts project Default state.
- Produces: list/get project queries including implicit Default access.

- [ ] Write failing tests for implicit Default Viewer access.
- [ ] Write failing test for immediate access movement after Default change.
- [ ] Run tests and confirm expected failures.
- [ ] Implement dynamic Default access without membership-row migration.
- [ ] Remove new-member Default membership writes.
- [ ] Run focused tests and confirm pass.

### Task 3: Normalize Organization Role Transitions

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_organization_member_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_project_service.py`
- Test: `backend/tests/test_organization_member_error_contract.py`

**Interfaces:**
- Produces: promotion cleanup and demotion-to-implicit-default behavior.

- [ ] Write failing promotion and demotion tests.
- [ ] Run tests and confirm expected failures.
- [ ] Clear redundant grants on promotion.
- [ ] Prevent historical grants from silently reactivating on demotion.
- [ ] Run focused tests and confirm pass.

### Task 4: Apply Operation-Specific Authorization

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Modify: `backend/app/joysafeter_shared/common/joysafeter_auth/dependencies.py`
- Test: `backend/tests/test_project_admin_dependency_contract.py`
- Test: `backend/tests/test_project_lifecycle_active_tasks.py`
- Test: `backend/tests/test_project_member_management.py`

**Interfaces:**
- Produces: path-scoped Project Admin guards.
- Produces: separate name, slug, operations, and organization-governance authorization.

- [ ] Write failing Project Admin rename and trigger tests.
- [ ] Write failing Project Admin slug/default/archive denial tests.
- [ ] Run tests and confirm expected failures.
- [ ] Split project update authorization by changed field.
- [ ] Apply Project Admin to project access and token management.
- [ ] Run focused tests and confirm pass.

### Task 5: Enforce Project Creation Policy

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_project_service.py`
- Test: `backend/tests/test_project_lifecycle_active_tasks.py`

**Interfaces:**
- Consumes: `Organization.project_creation_policy`
- Produces: member project creation with explicit Project Admin grant.

- [ ] Write failing policy tests for both modes.
- [ ] Run tests and confirm expected failures.
- [ ] Enforce policy and persist creator provenance.
- [ ] Avoid redundant owner/admin project grants.
- [ ] Run focused tests and confirm pass.

### Task 6: Validate Permission Model

**Files:**
- Test: backend organization/project test suites.

- [ ] Run focused authorization suites.
- [ ] Run Ruff on changed backend files.
- [ ] Run Alembic head validation.
- [ ] Run `git diff --check`.
