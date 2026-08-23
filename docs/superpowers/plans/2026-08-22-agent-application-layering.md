# Agent Application Layering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mixed Domain Agent service with explicit Domain policies, an Infrastructure repository, and complete Application query, command, and lifecycle services.

**Architecture:** Pure Agent transformations and validation rules live in `joysafeter_domain/agents`. SQLAlchemy persistence lives in `joysafeter_infrastructure/agents`. Application services own transactions, dependency locking, external lifecycle effects, and stable error translation; API and worker callers use those services.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy asyncio, PostgreSQL, pytest, Ruff

**Spec:** `docs/superpowers/specs/2026-08-22-agent-application-layering-design.md`

## Global Constraints

- Preserve all public REST schemas, database columns, typed ids, and Agent snapshot formats.
- Preserve Trigger → Agent lifecycle lock order and final blocker rechecks.
- Preserve Credential reference and encryption compatibility contracts.
- Do not retain the old Domain service path or method shims.
- Do not modify `.deps/SkillSpector` or `backend/tests/test_rebin_dockerfiles.py`.
- Run database suites against an isolated PostgreSQL database and remove it afterward.
- Do not commit changes.

---

### Task 1: Establish Architecture and Regression Gates

**Files:**
- Modify: `backend/tests/test_credential_application_boundaries.py`
- Modify: `backend/tests/test_agent_model_credential_ref.py`
- Modify: `backend/tests/test_agent_environment_ref_validation.py`

**Interfaces:**
- Requires `AgentCommandService`, `AgentQueryService`, and `AgentLifecycleService` under `joysafeter_application.agents`.
- Rejects the old `joysafeter_domain.services.joysafeter_agent_service` path and all Domain → Application imports.

- [ ] Add a failing AST boundary test for the new ownership map.
- [ ] Add a failing update test proving engine/model changes revalidate the retained credential.
- [ ] Add a failing PostgreSQL race test proving Environment archive and Agent binding serialize.
- [ ] Run the focused tests and confirm failures are architectural or behavioral, not fixture errors.

### Task 2: Extract Pure Agent Domain Modules

**Files:**
- Create: `backend/app/joysafeter_domain/agents/__init__.py`
- Create: `backend/app/joysafeter_domain/agents/assets.py`
- Create: `backend/app/joysafeter_domain/agents/configuration_policy.py`
- Create: `backend/app/joysafeter_domain/agents/snapshots.py`
- Modify: `backend/tests/services/test_agent_skill_ref_gate.py`

**Interfaces:**
- `merge_agent_assets(skills, agents, commands) -> list[dict]`
- `split_agent_assets(merged) -> tuple[list[dict], list[dict], list[dict]]`
- `AgentConfigurationPolicy.validate_mcp_servers(..., require_https: bool) -> None`
- `AgentConfigurationPolicy.validate_tool_mcp_references(...) -> None`
- Snapshot helpers preserve existing document shapes.

- [ ] Move pure transformations without compatibility aliases.
- [ ] Move MCP and tool-reference rules out of the API router.
- [ ] Update focused unit tests to import public Domain names.
- [ ] Run no-database policy and snapshot tests.

### Task 3: Add the SQLAlchemy Agent Repository

**Files:**
- Create: `backend/app/joysafeter_application/agents/ports.py`
- Create: `backend/app/joysafeter_infrastructure/agents/__init__.py`
- Create: `backend/app/joysafeter_infrastructure/agents/sqlalchemy_repository.py`

**Interfaces:**
- Repository reads and locks Agents, Environments, Sessions, Tasks, and versions.
- Repository writes Agent versions, archives eligible Sessions, and hard-deletes Agent-owned rows.
- Repository methods flush but never commit.

- [ ] Define the Application-owned repository protocol.
- [ ] Move SQL query and mutation primitives into the Infrastructure adapter.
- [ ] Preserve project scoping, soft-delete filters, pagination, and typed ids.
- [ ] Add focused repository tests for locks, counts, versions, and deletion.

### Task 4: Implement Agent Application Services

**Files:**
- Create: `backend/app/joysafeter_application/agents/__init__.py`
- Create: `backend/app/joysafeter_application/agents/query_service.py`
- Create: `backend/app/joysafeter_application/agents/command_service.py`
- Create: `backend/app/joysafeter_application/agents/lifecycle_service.py`
- Create: `backend/app/joysafeter_application/agents/composition.py`

**Interfaces:**
- Query service exposes the existing read/snapshot contract.
- Command service exposes `create_agent` and `update_agent`.
- Lifecycle service exposes delete, archive, restore, hard-delete, and Session cleanup use cases.
- Production composition supplies SQLAlchemy, Credential, runtime cancellation, sandbox, and identity adapters.

- [ ] Implement query delegation without transaction side effects.
- [ ] Implement create with Environment → Credential locking and one commit.
- [ ] Implement update with Agent → Environment → sorted Credentials locking.
- [ ] Revalidate retained credentials when engine or model changes.
- [ ] Preserve no-op version behavior and structured name/version errors.
- [ ] Move lifecycle orchestration and external side effects from the API.

### Task 5: Migrate Callers and Remove Legacy Service

**Files:**
- Modify: `backend/app/joysafeter_api/api/v1/agents.py`
- Modify: `backend/app/joysafeter_api/api/v1/sessions.py`
- Modify: `backend/app/joysafeter_api/api/v1/tasks.py`
- Modify: `backend/app/joysafeter_worker/scheduler/loop.py`
- Modify: affected Agent, Credential, Session, Trigger, and architecture tests
- Delete: `backend/app/joysafeter_domain/services/joysafeter_agent_service.py`

**Interfaces:**
- API routes retain unchanged request/response/error contracts.
- Read-only consumers use `AgentQueryService`.
- Command and lifecycle callers use their dedicated Application services.

- [ ] Replace production imports and method calls.
- [ ] Replace test imports and monkeypatch targets.
- [ ] Remove API business helpers moved to Domain/Application.
- [ ] Delete the old service and assert no legacy references remain.

### Task 6: Verify and Record Evidence

**Files:**
- Modify: `docs/superpowers/evidence/2026-08-22-credential-lifecycle-deep-audit.md`

**Interfaces:**
- Evidence records zero Domain → Application imports and exact PostgreSQL results.

- [ ] Run focused Ruff, format, and compile checks.
- [ ] Run architecture and collection checks.
- [ ] Run Agent/credential/lifecycle suites against isolated PostgreSQL.
- [ ] Update evidence with exact results and remaining unrelated failures.
- [ ] Drop the isolated database and verify removal.
