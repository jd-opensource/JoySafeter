# Credential Runtime and Lifecycle Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make MCP member lifecycle and runtime refresh behavior consistent without breaking stored reference compatibility.

**Architecture:** Keep lifecycle decisions in the Python domain/application boundary and runtime filtering in the Rust credential store. Preserve current APIs while making group deletion transactional and distinguishing egress refresh from unsupported direct environment propagation.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, PostgreSQL, Rust, SQLx, pytest, Cargo test.

**Spec:** `docs/superpowers/specs/2026-08-21-credential-runtime-lifecycle-closure-design.md`

## Global Constraints

- Do not alter existing user changes in `.deps/SkillSpector` or `backend/tests/test_rebin_dockerfiles.py`.
- Preserve v1 credential-reference persistence.
- Add regression tests before each production change.
- Do not commit unless explicitly requested.

---

### Task 1: Active MCP Runtime Membership

**Files:**
- Modify: `backend/tests/test_mcp_archived_credential_runtime_contract.py`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/store.rs`

**Interfaces:**
- Consumes: `CredentialStore::load_session_mcp_members`
- Produces: active-only MCP member query semantics

- [x] Add a contract test requiring inactive-member filtering in SQL.
- [x] Run the test and verify it fails.
- [x] Filter archived and deleted members in the join while preserving empty groups.
- [x] Run Python contract and Rust credential tests.

### Task 2: Group Delete Ownership Closure

**Files:**
- Modify: `backend/tests/test_credential_group_service.py`
- Modify: `backend/app/joysafeter_infrastructure/credentials/sqlalchemy_repository.py`

**Interfaces:**
- Consumes: `SqlAlchemyCredentialRepository.delete_group`
- Produces: transactional soft deletion of group-owned members

- [x] Add a failing test proving group deletion hides and releases all members.
- [x] Run the test and verify it fails.
- [x] Soft-delete non-deleted members before deleting the group.
- [x] Run group and credential lifecycle tests.

### Task 3: Group Restore With Archived Members

**Files:**
- Modify: `backend/tests/test_credential_group_service.py`
- Modify: `backend/app/joysafeter_domain/credentials/policies.py`

**Interfaces:**
- Consumes: `validate_group_restore`
- Produces: validation of active members while retaining archived member history

- [x] Add a failing test for restoring a group with an archived member.
- [x] Run the test and verify it fails.
- [x] Ignore archived members during runnable-member validation.
- [x] Run domain and group lifecycle tests.

### Task 4: Runtime Refresh Semantics

**Files:**
- Modify: targeted credential impact and refresh tests
- Modify: credential impact/refresh implementation selected after test evidence

**Interfaces:**
- Consumes: `CredentialImpact`, `mark_live_sandboxes_pending`
- Produces: no false egress-refresh claim for direct environment injection

- [x] Add a failing test for direct-injection mutation behavior.
- [x] Select `REVALIDATE_ON_ACTIVATION` without changing storage schemas.
- [x] Skip network pending/nudges and audit restart-required environment updates.
- [x] Run atomic refresh and runtime tests.

### Task 5: Cross-Layer Verification

**Files:**
- Test only

**Interfaces:**
- Consumes: all prior tasks
- Produces: verified P0 lifecycle closure

- [x] Run focused Python credential tests.
- [x] Run focused Rust credential tests.
- [x] Run frontend tests and TypeScript type checking.
- [x] Review diff and preserve pre-existing user changes.
