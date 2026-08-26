# Tenant and Authentication ID Convergence Implementation Plan

> **For agentic workers:** Execute inline in the current feature worktree. Do not create commits, reset unrelated changes, or use compatibility readers.

**Goal:** Finish global typed-ID convergence for tenant, authentication, audit, event, and network-policy identities while removing the disconnected Observation persistence prototype.

**Architecture:** Shared Python/Rust/frontend typed-ID inventories define canonical public prefixes while PostgreSQL stores native UUIDs. Application/event producers create IDs before persistence; repositories, ORM defaults, SQL functions, and consumers never invent identity. Public readers are strict and the deployment is a coordinated cutover with old sessions invalidated.

**Tech Stack:** Python 3.12+/FastAPI/Pydantic/SQLAlchemy/Alembic, PostgreSQL, Rust/sqlx, TypeScript/React/Next.js/Vitest

**Spec:** `docs/superpowers/specs/2026-08-25-tenant-auth-id-convergence-design.md`

## Global Constraints

- Preserve unrelated worktree changes and the MCP matrix suite.
- Do not modify `.deps/SkillSpector`.
- Use semantic edits only; do not perform repository-wide mechanical replacement.
- PostgreSQL stores native UUIDs; public boundaries use strict prefixed IDs.
- Do not add runtime dual-read, fallback, or compatibility shims.
- Run backend pytest commands from `backend/`.
- Do not commit changes.

---

### Task 1: Add Failing Architecture and Codec Tests

**Files:**
- Modify: `backend/tests/test_entity_ids.py`
- Modify: `backend/tests/test_typed_id_architecture.py`
- Modify: `frontend/types/entity-id.test.ts`
- Modify: `frontend/types/entity-id-architecture.test.ts`
- Modify: `shared/rust/joysafeter-entity-id/src/lib.rs`

**Interfaces:**
- Produces the exact new ID type and prefix inventory required by later tasks.
- Produces guards for typed model columns, explicit lifecycle creation, and forbidden fallback generation.

- [ ] Add failing codec tests for all new Python, Rust, and frontend ID types.
- [ ] Add failing architecture guards for duplicate `ProjectId`, raw tenant IDs, implicit ID creation, missing event IDs, and SQL-generated entity IDs.
- [ ] Run each focused test and confirm it fails for the intended missing contract.

### Task 2: Extend Shared ID Sources

**Files:**
- Modify: `backend/app/joysafeter_shared/ids.py`
- Modify: `shared/rust/joysafeter-entity-id/src/lib.rs`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/ids.rs`
- Modify: `frontend/types/entity-id.ts`
- Modify: `frontend/test-utils/entity-ids.ts`

**Interfaces:**
- Produces concrete ID classes/newtypes/brands and strict parse functions.
- PostgreSQL conversion continues through `EntityIdType` and sqlx UUID adapters.

- [ ] Implement the new shared ID types and prefix registries.
- [ ] Add frontend strict parse functions only for IDs exposed by APIs.
- [ ] Run codec tests until green.

### Task 3: Type Tenant and Authentication Models

**Files:**
- Modify: `backend/app/joysafeter_domain/models/joysafeter_auth.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_organization.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_project.py`
- Modify: `backend/app/joysafeter_domain/models/joysafeter_oauth_account.py`
- Modify: tenant/user/project reference columns under `backend/app/joysafeter_domain/models/`

**Interfaces:**
- Models consume concrete IDs and `EntityIdType`.
- Constructors require explicit IDs; no model default creates identity.

- [ ] Add failing model metadata tests for every monomorphic identity column.
- [ ] Convert PK/FK and monomorphic snapshot fields to concrete ID types.
- [ ] Keep third-party, runtime, and polymorphic identifiers semantically distinct.
- [ ] Run model and architecture tests until green.

### Task 3A: Remove Disconnected Observation Persistence

**Files:**
- Delete: `backend/app/joysafeter_shared/observation/`
- Create: `backend/app/joysafeter_shared/telemetry/`
- Modify: `backend/app/joysafeter_shared/runtime/lifecycle.py`
- Modify: analytics backend/frontend contracts and architecture documentation

**Interfaces:**
- Request tracing keeps the global OTel provider and optional OTLP export.
- The unused ORM, processors, placeholder endpoint, and frontend waterfall are removed.
- Analytics `trace_id` remains the existing `TaskId`; HTTP diagnostic trace IDs remain OTel hex values.

- [x] Add failing architecture guards for the orphan directory and placeholder API/UI.
- [x] Move the generic tracer provider into `joysafeter_shared/telemetry/`.
- [x] Delete the disconnected persistence and broadcast implementation.
- [x] Remove the placeholder analytics endpoint and frontend waterfall.
- [x] Synchronize architecture documentation and run focused verification.

### Task 4: Move Identity Creation to Lifecycle Owners

**Files:**
- Modify: `backend/app/joysafeter_domain/services/joysafeter_auth_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_organization_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_organization_member_service.py`
- Modify: `backend/app/joysafeter_domain/services/joysafeter_project_service.py`
- Modify: `backend/app/joysafeter_identity_federation/infrastructure/account_gateway.py`
- Modify: auth/session repositories and affected tests/fixtures

**Interfaces:**
- Creation methods accept and return concrete tenant/auth IDs.
- Repositories persist supplied identity and never allocate it.

- [ ] Add failing lifecycle tests for each creation path.
- [ ] Generate each ID before constructing the model or invoking persistence.
- [ ] Remove `_generate_str_id`, raw UUID generation, and optional ID injection paths.
- [ ] Run focused auth/organization/project/federation tests until green.

### Task 5: Type Authentication and Public Contracts

**Files:**
- Modify: `backend/app/joysafeter_shared/security/__init__.py`
- Modify: `backend/app/joysafeter_shared/common/joysafeter_auth/context.py`
- Modify: `backend/app/joysafeter_shared/common/joysafeter_auth/dependencies.py`
- Modify: `backend/app/joysafeter_api/api/v1/auth.py`
- Modify: `backend/app/joysafeter_api/api/v1/organizations.py`
- Modify: `backend/app/joysafeter_api/api/v1/oauth.py`
- Modify: identity-federation domain/application ports and models
- Modify: affected API schemas and tests

**Interfaces:**
- JWT claims and REST paths consume and emit canonical prefixed IDs.
- Bare UUID and wrong-prefix input fails before repository access.

- [ ] Add failing JWT and REST boundary tests.
- [ ] Type token creation, payload decoding, auth context, routes, and response schemas.
- [ ] Update service/repository signatures without adding string bridges.
- [ ] Run focused auth/API/identity-federation tests until green.

### Task 6: Remove False Project Identity

**Files:**
- Modify: `backend/app/joysafeter_domain/credentials/bindings.py`
- Modify: `backend/app/joysafeter_application/environments/credential_service.py`
- Modify: associated credential/environment tests

**Interfaces:**
- Produces `CredentialBindingFingerprint`, independent of tenant identity.
- Environment impact comparison no longer accepts or fabricates `ProjectId`.

- [ ] Add a failing test proving comparison does not need a project ID.
- [ ] Implement the project-free fingerprint and remove the fake ID constant.
- [ ] Run credential/environment tests until green.

### Task 7: Converge Rust Project, Event, and Policy IDs

**Files:**
- Modify: `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/record.rs`
- Modify: affected Rust credential modules
- Modify: `backend/app/joysafeter_orchestrator_rs/src/events/envelope.rs`
- Modify: `backend/app/joysafeter_worker/events/stream_consumer.py`
- Modify: `backend/app/joysafeter_orchestrator_rs/src/db/queries/sandbox.rs`
- Modify: affected Rust/Python tests

**Interfaces:**
- Credential runtime consumes shared `ProjectId`.
- `EventEnvelope.event_id` is required and producer-owned.
- Network-policy SQL receives an explicit `SandboxNetworkPolicyId`.

- [ ] Add failing tests for strict project parsing, missing event-ID rejection, and explicit network-policy IDs.
- [ ] Remove local Rust `ProjectId` and use the shared crate.
- [ ] Remove Worker fallback and require producer event IDs.
- [ ] Replace `gen_random_uuid()` with a bound typed ID created by the orchestrator operation.
- [ ] Run focused orchestrator and worker tests until green.

### Task 8: Add Coordinated UUID Migration

**Files:**
- Create: `backend/alembic/versions/20260825_000003_type_tenant_auth_ids.py`
- Create: `backend/tests/test_type_tenant_auth_ids_migration.py`
- Modify: migration integration helpers when required

**Interfaces:**
- Converts all monomorphic tenant/auth identity columns to native UUID.
- Preserves constraints and rejects malformed legacy rows.
- Invalidates all persisted authentication sessions.

- [ ] Add failing migration tests for valid conversion, malformed data, constraints, snapshot columns, and session invalidation.
- [ ] Implement preflight validation and ordered constraint/type conversion.
- [ ] Implement downgrade casts without restoring deleted sessions.
- [ ] Run migration tests against PostgreSQL until green.

### Task 9: Type Frontend Tenant and Auth State

**Files:**
- Modify: `frontend/types/entity-id.ts`
- Modify: `frontend/types/managed.ts`
- Modify: `frontend/lib/auth/api-client.ts`
- Modify: `frontend/stores/auth/store.ts`
- Modify: `frontend/stores/managed/project-store.ts`
- Modify: `frontend/providers/project-provider.tsx`
- Modify: tenant/project routes and components
- Rename: `frontend/lib/managed/id.ts` to `frontend/lib/managed/entity-id-display.ts`

**Interfaces:**
- Frontend API results and state carry branded IDs.
- Persisted old auth/project state is invalidated rather than converted.

- [ ] Add failing parser, route, store-version, and architecture tests.
- [ ] Type response parsers and state boundaries.
- [ ] Rename the display helper and remove bare UUID extraction as a public API.
- [ ] Update imports and route parameter parsing.
- [ ] Run focused frontend tests and type-check until green.

### Task 10: Update Documentation and Run Completion Audit

**Files:**
- Modify: `docs/superpowers/specs/2026-08-24-global-typed-id-unification-design.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ARCHITECTURE_CN.md`
- Modify: `docs/api/openapi.md`
- Modify: `scripts/check_documentation_contracts.py`
- Modify: architecture tests in backend/frontend

**Interfaces:**
- Normative documentation states the same prefixes, representations, owners, and failure behavior as code.
- Scans distinguish legitimate historical/Kubernetes terminology from executable legacy identity contracts.

- [ ] Remove the incorrect user/organization/project non-goal.
- [ ] Document the final lifecycle and boundary matrix.
- [ ] Run targeted suites, then full backend/frontend/orchestrator/runner/documentation checks.
- [ ] Perform final repository-wide semantic scans covering contents, filenames, and directories.
