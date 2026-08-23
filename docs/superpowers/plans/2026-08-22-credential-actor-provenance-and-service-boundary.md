# Credential Actor Provenance and Service Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve the initiating actor across every credential mutation and material-use path while deleting dynamic credential-service compatibility facades.

**Architecture:** Require explicit actor construction at composition boundaries, thread it through Trigger execution into Session snapshot creation, persist the complete access actor in PostgreSQL, and expose only explicit Application methods. Existing REST, typed-ID, transaction, lock-order, and persisted credential contracts remain unchanged.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy async, Alembic, PostgreSQL, pytest, Ruff, Docker/testcontainers.

**Spec:** `docs/superpowers/specs/2026-08-22-credential-actor-provenance-and-service-boundary-design.md`

## Global Constraints

- Do not modify `.deps/SkillSpector` or `backend/tests/test_rebin_dockerfiles.py`.
- Do not add compatibility shims, aliases, dynamic forwarding, or duplicate old/new service paths.
- Preserve public REST paths, request/response payloads, structured error codes, typed IDs, credential encryption format, snapshot format, and lock order.
- Use real PostgreSQL for behavioral and migration regression.
- Do not commit or reset the existing worktree.

---

### Task 1: Lock Trigger Actor Propagation

**Files:**
- Modify: `backend/tests/test_trigger_http_e2e_contract.py`
- Modify: `backend/tests/test_trigger_webhook_route_contract.py`
- Modify: `backend/tests/test_trigger_project_lifecycle.py`
- Modify: `backend/app/joysafeter_api/api/v1/triggers.py`
- Modify: `backend/app/joysafeter_application/triggers/service.py`
- Modify: `backend/app/joysafeter_application/triggers/fire_service.py`
- Modify: `backend/app/joysafeter_application/triggers/execution_service.py`

**Interfaces:**
- Consumes: `CredentialAuditActor`, `credential_audit_actor(request, auth_ctx)`.
- Produces: `TriggerFireService(..., audit_actor: CredentialAuditActor)` and `AgentTriggerExecutor(..., audit_actor: CredentialAuditActor)`.

- [x] Add PostgreSQL tests asserting `session.snapshot.created` records the authenticated user for manual and test-webhook routes.
- [x] Add PostgreSQL test asserting public webhook Session snapshot audit records `principal_type="webhook_request"`.
- [x] Add scheduler test asserting the explicit `system/trigger_scheduler` actor.
- [x] Run the new tests and verify they fail with `session_service` or missing actor propagation.
- [x] Thread the same actor through Trigger Application, fire service, executor, and Session creation.
- [x] Make manual and test-fire routes construct the request actor; make scheduler construction explicit.
- [x] Re-run the focused Trigger tests and verify all pass.

### Task 2: Make Actor Composition Explicit

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/composition.py`
- Modify: `backend/app/joysafeter_application/sessions/creation_service.py`
- Modify: `backend/app/joysafeter_application/environments/credential_service.py`
- Modify: `backend/app/joysafeter_application/triggers/service.py`
- Modify: `backend/app/joysafeter_application/credentials/webhook_auth_service.py`
- Modify: `backend/app/joysafeter_infrastructure/agents/credential_binding_adapter.py`
- Modify: all direct callers of `compose_credential_application`
- Test: `backend/tests/test_credential_application_boundaries.py`

**Interfaces:**
- Consumes: explicit `CredentialAuditActor` supplied by each outer boundary.
- Produces: `compose_credential_application(db, *, audit_actor, auto_commit=True, ...)` with no default.

- [x] Add an architecture test that rejects an optional/default `audit_actor` in the composition root.
- [x] Add a source test that every production composition call supplies `audit_actor=`.
- [x] Run the tests and verify they fail against the current optional fallback.
- [x] Require `audit_actor` in the composition root and update every caller with a named request or system actor.
- [x] Preserve explicit identities: `session_service`, `environment_service`, `trigger_service`, `trigger_scheduler`, `agent_binding`, and request-derived actors.
- [x] Re-run boundary and caller suites.

### Task 3: Remove Credential Compatibility Facades

**Files:**
- Delete: `backend/app/joysafeter_application/credentials/management_service.py`
- Modify: `backend/app/joysafeter_application/credentials/resource_service.py`
- Modify: `backend/app/joysafeter_application/credentials/group_service.py`
- Modify: `backend/app/joysafeter_application/credentials/composition.py`
- Modify: `backend/app/joysafeter_api/api/v1/credentials.py`
- Modify: `backend/app/joysafeter_api/api/v1/credential_groups.py`
- Modify: `backend/app/joysafeter_api/api/v1/model_connection_summary.py`
- Modify: tests importing `management_service`
- Test: `backend/tests/test_credential_application_boundaries.py`

**Interfaces:**
- Consumes: `CredentialApplication.resource_service`, `.group_service`, and `.lifecycle`.
- Produces: explicit `CredentialResourceService.get_or_raise`, `get_masked`, query, command, and lifecycle entry points without dynamic delegation.

- [x] Add architecture tests requiring `management_service.py` to be absent and banning `__getattr__` in Credential Application services.
- [x] Add tests proving every API-used method exists explicitly on the Application service.
- [x] Run the tests and verify they fail while the facades remain.
- [x] Add explicit Application methods currently reached through dynamic forwarding.
- [x] Migrate production and test imports to the composition root or explicit services.
- [x] Remove both `__getattr__` implementations, compatibility-only nudge forwarding, and `management_service.py`.
- [x] Run Credential, Group, Environment, Agent, Session, Trigger, and architecture tests.

### Task 4: Complete Group Membership Audit Context

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/ports.py`
- Modify: `backend/app/joysafeter_application/credentials/resource_service.py`
- Modify: `backend/app/joysafeter_application/credentials/group_service.py`
- Modify: `backend/tests/test_credential_group_service.py`
- Modify: `backend/tests/test_credentials_api.py`

**Interfaces:**
- Consumes: `CredentialAuditEntry.details`.
- Produces: membership audit events with `target_id=<credential_id>` and `details.credential_group_id=<group_id>`.

- [x] Add tests for add, archive, and remove membership events with both identifiers.
- [x] Run the tests and verify `credential_group_id` is missing.
- [x] Allow `_mutate` callers to supply immutable non-sensitive audit details.
- [x] Add `credential_group_id` to all membership audit entries.
- [x] Re-run service and HTTP audit tests.

### Task 5: Persist Complete Access Actor Context

**Files:**
- Modify: `backend/alembic/versions/20260822_000001_credential_access_audit.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_credential_access_audit.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/access_audit_adapter.py`
- Modify: `backend/tests/test_credential_access_audit_model.py`
- Modify: `backend/tests/test_credential_material_access_audit.py`
- Modify: `backend/tests/test_unified_credential_migration.py`

**Interfaces:**
- Consumes: complete `CredentialAuditActor` already present on `CredentialAccessAuditEntry`.
- Produces: nullable `user_id`, `org_id`, `role`, `ip_address`, and `user_agent` columns plus principal/time index in the not-yet-baselined access-audit migration.

- [x] Add model and adapter tests for all actor fields.
- [x] Add migration tests for upgrade, historical null rows, indexed principal lookup, and downgrade.
- [x] Run the tests and verify the fields and migration are absent.
- [x] Add the SQLAlchemy model columns and adapter mappings.
- [x] Complete Alembic migration `20260822_000001` in place; do not create a redundant follow-up revision before the original migration is baselined.
- [x] Run migration tests against a disposable PostgreSQL database.

### Task 6: Close Documentation and Cleanup

**Files:**
- Modify: `docs/superpowers/evidence/2026-08-22-credential-lifecycle-deep-audit.md`
- Modify: architecture tests that inventory Credential paths

**Interfaces:**
- Consumes: final implementation and regression evidence.
- Produces: an accurate current-state audit with no stale remediation item.

- [x] Update the evidence document with actor propagation, facade deletion, schema migration, and exact test counts.
- [x] Verify no production reference remains to `management_service`, dynamic Credential `__getattr__`, or generic implicit actor fallback.
- [x] Run targeted Ruff, format, compileall, Alembic heads, architecture tests, and `git diff --check`.
- [x] Run the combined Credential/Agent/Environment/Session/Trigger PostgreSQL regression.
- [x] Remove generated `__pycache__`, `.pyc`, `.pyo`, and disposable databases, then verify absence.
