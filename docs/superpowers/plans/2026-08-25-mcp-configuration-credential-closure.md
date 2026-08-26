# MCP Configuration and Credential Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Agent MCP declarations, MCP credential groups, Session authorization, runtime matching, CLI input, frontend guidance, and documentation obey one canonical contract.

**Architecture:** Agent configuration owns server declarations, credential groups own encrypted HTTP authentication material, Sessions own per-run group grants, and the orchestrator owns final URL-based resolution. Python preflight and mutation guards will mirror the Rust runtime planner instead of treating Agent declarations as URL conflicts.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Rust, Tonic/Protobuf, React 19, Next.js, TanStack Query, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-mcp-configuration-credential-closure-design.md`

## Global Constraints

- Preserve unrelated uncommitted typed-ID and environment-link changes.
- Do not expose plaintext credential material outside the credential access boundary.
- Keep Python, Rust, frontend, CLI, documentation, and tests on one MCP URL/authentication contract.
- Run backend pytest commands from `backend/`.
- Do not commit changes unless explicitly requested.

---

### Task 1: Domain Session Matching Contract

**Files:**
- Modify: `backend/app/joysafeter_domain/credentials/bindings.py`
- Modify: `backend/app/joysafeter_domain/credentials/policies.py`
- Modify: `backend/app/joysafeter_domain/credentials/__init__.py`
- Test: `backend/tests/test_credential_domain_core.py`

**Interfaces:**
- Produces a typed Agent MCP endpoint requirement carrying normalized URL and auth requirement.
- Produces validation that only checks credentials relevant to declared Agent endpoints.

- [ ] Write failing tests for required coverage, optional coverage, none-ignore, relevant duplicates, and unrelated duplicates.
- [ ] Run the focused domain tests and confirm the expected failures.
- [ ] Replace `declared_server_urls` conflict semantics with endpoint coverage semantics.
- [ ] Run focused domain tests to green.

### Task 2: Session and Mutation Preflight

**Files:**
- Modify: `backend/app/joysafeter_application/credentials/snapshot_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_credential_group_invariants.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`
- Modify: `backend/app/joysafeter_shared/common/error_catalog.py`
- Test: `backend/tests/test_session_credential_groups.py`
- Test: `backend/tests/test_credential_group_service.py`
- Test: `backend/tests/test_credential_snapshot_linearization.py`

**Interfaces:**
- Consumes Agent snapshot `mcp_servers` and selected group members.
- Produces `SESSION_MCP_CREDENTIAL_REQUIRED` for missing required credentials and retains `CREDENTIAL_GROUP_URL_CONFLICT` for ambiguous relevant credentials.

- [ ] Rewrite Session regression tests around the canonical matching contract.
- [ ] Add bound-session mutation tests for first-match allowed and relevant duplicate rejected.
- [ ] Run focused tests and confirm failures.
- [ ] Implement Session coverage extraction and validation.
- [ ] Implement relevance-aware member add/restore checks.
- [ ] Run focused tests to green.

### Task 3: Agent and CLI Transport Contract

**Files:**
- Modify: `backend/app/joysafeter_domain/agents/configuration_policy.py`
- Modify: `backend/tests/test_agent_environment_ref_validation.py`
- Modify: `sandbox-runner/crates/joysafeter-ctl/src/manifest.rs`
- Modify: `sandbox-runner/crates/joysafeter-ctl/src/commands/apply.rs`
- Modify: `sandbox-runner/crates/joysafeter-ctl/src/commands/create.rs`
- Test: colocated Rust unit tests.

**Interfaces:**
- Produces one supported transport/auth matrix: streamable HTTP with all requirements; SSE with `none`; local stdio without remote auth fields.

- [ ] Add failing Python and Rust tests for invalid SSE authentication requirements.
- [ ] Run focused tests and confirm failures.
- [ ] Enforce the matrix in Agent policy and CLI manifest parsing.
- [ ] Update interactive CLI prompts.
- [ ] Run focused tests to green.

### Task 4: Frontend Canonical Matching and Guidance

**Files:**
- Create: `frontend/lib/managed/mcp-credential-coverage.ts`
- Create: `frontend/lib/managed/mcp-credential-coverage.test.ts`
- Modify: `frontend/lib/managed/quickstart-capabilities.ts`
- Modify: `frontend/lib/managed/quickstart-capabilities.test.ts`
- Modify: `frontend/components/managed/agent/mcp-server-editor.tsx`
- Modify: `frontend/components/managed/credentials/create-mcp-member-dialog.tsx`
- Modify: `frontend/app/managed/sessions/components/create-session-dialog.tsx`
- Modify: relevant component tests and locale files.

**Interfaces:**
- Produces canonical frontend URL normalization and a pure coverage summary for Agent servers plus selected credential members.
- Session UI consumes existing credential-group member endpoints; no new public API is introduced.

- [ ] Add failing canonical normalization and coverage tests.
- [ ] Add failing Agent editor SSE behavior tests.
- [ ] Add failing Session preflight component tests.
- [ ] Run focused Vitest tests and confirm failures.
- [ ] Implement the pure helper and update Quickstart.
- [ ] Add Agent and credential boundary copy.
- [ ] Fetch selected group members in parallel and render/block on compatibility status.
- [ ] Run focused frontend tests to green.

### Task 5: Contract, Migration, and Documentation Closure

**Files:**
- Create: `backend/alembic/versions/20260825_000005_validate_mcp_transport_auth_contract.py`
- Modify: `backend/tests/test_mcp_canonical_architecture.py`
- Modify: `tests/mcp_connection_matrix/test_l2_contract.py`
- Modify: `tests/mcp_connection_matrix/test_l3_live.py`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE_CN.md`
- Modify: `docs/tutorials/02-mcp-service-setup.md`
- Modify: `docs/joysafeter-agent-environment-session-api.md`
- Modify: `docs/user-journey-quickstart.drawio`

**Interfaces:**
- Migration fails closed on persisted SSE declarations that request managed credentials.
- Contract tests express Agent declaration plus Session credential-group authorization.

- [ ] Add failing migration/architecture tests.
- [ ] Implement persisted-data preflight.
- [ ] Rewrite live contract tests to use the canonical flow.
- [ ] Update all user-facing terminology and examples.
- [ ] Run documentation contract checks.

### Task 6: Verification

**Files:**
- No production files.

- [ ] Run focused Python MCP tests.
- [ ] Run focused Rust orchestrator MCP tests.
- [ ] Run focused sandbox-runner/CLI tests.
- [ ] Run focused frontend tests, lint, and type-check.
- [ ] Run broader backend and Rust checks permitted by the current worktree.
- [ ] Run `git diff --check` and record unrelated blockers separately.
