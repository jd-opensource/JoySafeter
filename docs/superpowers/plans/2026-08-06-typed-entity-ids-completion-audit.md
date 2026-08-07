# Typed Entity IDs Completion Audit

**Date:** 2026-08-06
**Status:** Complete — all audited entity identities are typed across Python, frontend, and the Rust orchestrator
**Scope:** Backend API/domain/ORM, tests, frontend, and Rust orchestrator

## Decision

The identifier architecture is:

```text
public boundary: <entity-prefix><uuid>
        ↓ validation
application/domain: typed EntityId
        ↓ persistence or explicitly documented cross-language boundary
physical storage/protocol: UUID
```

An entity ID type does not replace the public prefix. It replaces untyped `str` and
`uuid.UUID` values inside application code. Prefix handling must be centralized
at boundary codecs, not repeated in services, routes, frontend helpers, or tests.

## Audit Evidence

- The branch contains end-to-end migrations for `AgentId`, `SessionId`, `TaskId`,
  `TriggerId`, `EnvironmentId`, `SecretId`, `VaultId`, `CredentialId`, `SandboxId`,
  `MemoryStoreId`, `MemoryId`, `MemoryVersionId`, `SkillId`, `SkillFileId`,
  `SkillSecurityScanId`, `SkillVersionId`, `SkillVersionFileId`, `SkillUsageId`, `FileId`,
  `SessionResourceId`, and `EventId`; no audited entity remains pending.
- Backend validation covers 997 tests: the prior 995-test full suite passed, both newly added
  architecture guards pass, and Ruff reports no errors across `backend/app` and `backend/tests`.
- The original targeted mypy audit reported 55 typed-ID errors. The core
  execution graph now reports zero; full-app mypy is blocked only by four
  pre-existing nullable-user errors in `auth.py`.
- Backend application code no longer declares migrated Agent/Session/Task/Trigger/Environment/Secret/Vault/Credential/Sandbox/Memory/Skill/File/SessionResource/Event
  identity parameters as `uuid.UUID`, `UUID`, `str`, or `Any`, except the documented polymorphic
  Session `environment_ref` schema boundary.
- Agent path validation now uses direct `AgentId` validation and is covered by
  the unified request-validation contract.
- Backend Agent/Session/Task/Trigger/Environment/Secret/Vault/Credential/Sandbox/Memory/Skill/File/SessionResource/Event fixtures now use typed IDs except for dedicated
  boundary-compatibility tests. An architecture guard rejects new raw core UUID
  annotations, legacy helpers, cross-entity persistence binds, and implicit Sandbox
  serialization at Redis/provider boundaries.
- The generic `same_id` string-comparison helper is removed. Physical UUID
  unwrapping accepts only `EntityId` or `uuid.UUID`; string compatibility remains
  isolated to explicit constructors and persistence adapters.
- The frontend preserves canonical `agent_`, `sess_`, `task_`, `trig_`, `env_`, `secret_`, `vault_`, `cred_`, `sbx_`, `memstore_`, `mem_`, `memver_`, `skill_`, `sklfile_`, `sklscan_`, `sklver_`, `sklvfile_`, `skluse_`, `file_`, `sesrsc_`, and `evt_` IDs through API
  paths and bodies. Prefix stripping remains available only for explicitly
  unaudited legacy resource families whose backend contracts are not migrated.
- Frontend `AgentId`, `SessionId`, `TaskId`, `TriggerId`, `EnvironmentId`, `SecretId`, `VaultId`, `CredentialId`, `SandboxId`, `MemoryStoreId`, `MemoryId`, `MemoryVersionId`, `SkillId`, `SkillFileId`, `SkillSecurityScanId`, `SkillVersionId`, `SkillVersionFileId`, `SkillUsageId`, `FileId`, `SessionResourceId`, and `EventId` are branded
  template-literal types with strict runtime parsers. Agent, Session, Trigger,
  Trigger-run/fire, and analytics contracts validate IDs at their API boundaries.
- Frontend core-ID fixtures are UUID-backed. A test-suite architecture guard
  rejects future `agent_a`, `sess_123`, and similar noncanonical fixtures.
- Agent and Session list/detail/create responses now cross dedicated runtime parsers, including
  nested Agent skill IDs, Session Agent/Vault IDs, and Session repository resource IDs.
- Full frontend validation passes: TypeScript, 256 tests, and the Next.js production build.
- Frontend Agent/Session/Environment route params are parsed once at the page boundary;
  Session SSE, Quickstart runtime flows, creation callbacks, Trigger form state,
  and React Query keys retain branded canonical IDs without prefix stripping.
- Analytics filters, calls, comparisons, alerts, rankings, and observation trace
  IDs cross the frontend API boundary through runtime parsers rather than generic
  branded-type assertions.
- Trigger list/detail/create/update/toggle/run/test-fire/history responses cross
  the frontend API boundary through runtime parsers; Trigger query keys, routes,
  cache equality, and webhook helpers retain the canonical prefixed ID.
- Environment and storage-mount responses cross the frontend API boundary through runtime parsers;
  environment list/detail/mutations, Quickstart, Session dialogs, Trigger options, and audit data
  retain `EnvironmentId` rather than reconstructing or stripping `env_`.
- Environment lookup deliberately accepts a canonical `env_<uuid>` or environment name. Bare UUID
  lookup is rejected so the polymorphic `environment_ref` cannot silently bypass entity discrimination.
- Secret ORM identity, schemas, routes, pagination cursors, error payloads, and services now use
  `SecretId`; the obsolete `parse_secret_id` dependency and manual `secret_{row.id}` formatting are removed.
- Secret list/detail/create/update/default responses are runtime-parsed in the frontend. CRUD routes,
  React Query keys, Environment selectors, and Skill authoring consumers preserve canonical `secret_` IDs.
- `secret_ref` remains intentionally name-based because it selects configured credentials by stable
  human-readable name; it is not conflated with Secret resource identity.
- Vault and nested Credential ORM fields, schemas, routes, cursors, services, errors, and frontend
  response parsers now retain `VaultId`/`CredentialId`; obsolete `parse_vault_id`/`parse_cred_id` are removed.
- Session `vault_ids` is validated as `list[VaultId]`, persisted as canonical strings in JSONB, and
  unwrapped by the Rust harness only at its SQL boundary; dedicated compatibility coverage retains
  readability for historical bare UUID JSONB values.
- Sandbox ORM/FK fields, schemas, routes, services, cancellation flows, Redis commands, Rust queries,
  scheduler/controllers/providers, and frontend network-policy diagnostics now retain `SandboxId`.
  Public values use `sbx_<uuid>`; database, Redis, protobuf, provider labels/names, runner environment
  variables, and Envoy resources explicitly unwrap to the bare UUID.
- Fourteen stale backend tests were corrected: fake Redis/runtime assertions now expect bare sandbox
  UUIDs, raw SQL race simulators bind `as_uuid(...)`, and public error/schema assertions retain
  canonical `sbx_<uuid>` values.
- The stale Alembic smoke test no longer hard-codes the former initial revision as the only head; it
  now proves the migration graph has one head, one root, and a contiguous linear chain.
- Memory Store/Memory/Memory Version ORM fields, schemas, routes, cursors, services, session/sandbox
  references, frontend responses, routes, request bodies, and fixtures now retain their matching typed IDs.
  Redis memory-update commands and runner protobuf mounts intentionally unwrap only `MemoryStoreId` to
  the bare UUID. Rust restores the type before subscription lookup; a regression test covers stores that
  share the same mount name so an update cannot leak across stores or disappear because mount names differ.
- The migration uncovered and fixed a production double-prefix defect in Skill
  impact references (`agent_agent_...` / `trig_trig_...`) and added a guard that
  rejects future manual re-prefixing of typed query rows.
- The Rust orchestrator now defines transparent `AgentId`, `SessionId`, `TaskId`, `EnvironmentId`,
  `VaultId`, `CredentialId`, `SandboxId`, `MemoryStoreId`, `MemoryId`, `MemoryVersionId`, all six
  Skill ID newtypes, `FileId`, `SessionResourceId`, and `EventId`. Models, queries, scheduler,
  resolver, controllers, event
  flow, gRPC harnesses, and DB tests use the matching core type; no migrated core
  identity annotations remain on `Uuid` inside the kernel.
- Rust entity IDs no longer implement `Deref<Uuid>`. Task subscriber maps retain `TaskId`,
  Environment lookup rejects bare UUIDs, Vault JSONB compatibility restores `VaultId` immediately,
  and Vault credential rows retain `CredentialId`.
- Redis keys/values and protobuf UUID fields are explicit physical adapters via
  `.as_uuid()`/`from_uuid()`, while public JSON/log formatting retains canonical
  `agent_`, `sess_`, `task_`, `sbx_`, `memstore_`, `mem_`, `memver_`, the six Skill prefixes,
  `file_`, `sesrsc_`, and `evt_`.
- Rust validation passes with `cargo fmt --check` and 171 tests.
- Skill list/detail, files, versions, immutable version-file snapshots, scans, lifecycle transitions,
  authoring save/scan flows, usage records, Agent pickers, routes, React Query state, and fixtures now
  runtime-parse and retain the matching branded ID. The migration also removed the pre-persistence
  import DTO's fabricated empty `id`/`skill_id` fields.

## P0 — Close the Backend Type Chain

The Skill slice is a six-identity migration, not a root-ID-only rename. Its canonical public
contracts are `SkillId` (`skill_`), `SkillFileId` (`sklfile_`), `SkillSecurityScanId`
(`sklscan_`), `SkillVersionId` (`sklver_`), `SkillVersionFileId` (`sklvfile_`), and
`SkillUsageId` (`skluse_`). ORM FKs, lifecycle/security services, Rust bundle loading, frontend
response parsers, and fixtures moved together; SQL/Redis/protobuf adapters remain bare UUID.

- [x] Change Agent-facing service and helper signatures from `uuid.UUID` to
      `AgentId`, including agent, session, task, trigger, sandbox, trigger-fire,
      runtime-gate, and task-submission services.
- [x] Change Session- and Task-facing service/event signatures exposed by the
      current mypy failures to `SessionId` and `TaskId`.
- [x] Remove application-layer `.uuid` unwrapping from the migrated core graph. Permit it only in
      `EntityIdType`, advisory-lock hashing, explicitly documented Redis/protobuf
      codecs, and other physical boundaries.
- [x] Replace `CreateSessionRequest`'s `_parse_agent_id()` round-trip
      (`AgentId -> UUID -> str -> AgentId`) with direct `AgentId` normalization.
- [x] Type all Agent-related request/query/response fields, including analytics
      filters/results and any agent reference that denotes a JoySafeter Agent.
- [x] Replace route `Depends(parse_agent_id)` usage with direct `AgentId` path
      validation, or keep only a thin typed dependency until final teardown.
- [x] Complete the Trigger migration across ORM, Task FK, schemas, routes,
      services, scheduler state, runtime gate, tests, and frontend.
- [x] Complete the Environment migration across ORM, schemas, routes, services,
      storage-mount audit records, tests, and frontend API/runtime boundaries.
- [x] Complete the Secret migration across ORM, schemas, routes, services, pagination,
      error contracts, tests, and frontend API/runtime boundaries.
- [x] Complete the Vault/Credential migration across ORM/FK types, nested routes, pagination,
      Session references, tests, frontend API/runtime boundaries, and Quickstart.
- [x] Complete the Sandbox migration across Python ORM/schemas/routes/services, runtime Redis
      commands, Rust models/kernel/providers, frontend diagnostics, and stale tests.
- [x] Complete the remaining entity migration from the primary implementation
      plan: Event. Memory, Skill, File, and SessionResource are also complete.
- [x] Remove obsolete application-level `parse_*` functions and inline prefix
      manipulation. The remaining Rust `parse_task_id` is an explicit queue
      boundary codec; `format_agent_id` and `same_id` are removed.
- [x] Treat bare UUID strings as a temporary compatibility policy only for
      unmigrated entity helpers. Typed Agent/Session/Task/Trigger/Environment/Secret/Vault/Credential/Sandbox/Memory/Skill/File/SessionResource public inputs require
      canonical prefixes. Constructors, ORM, Redis, and protobuf adapters retain
      explicit bare-UUID support at physical boundaries.

## P0 — Replace Outdated Tests

- [x] Move Agent invalid-ID coverage out of `test_id_helper_error_contract.py` and drive FastAPI/Pydantic
      request validation instead of calling legacy `parse_*` helpers directly.
- [x] Fix the stale “Task migration is a later task” test and construct the
      response with `TaskId`, not a bare task UUID.
- [x] Update Agent lifecycle, environment, trigger, task-identity, idempotency,
      and resource-reference tests to create and pass `AgentId` values explicitly.
- [x] Add ORM/type-boundary assertions that entity IDs reject cross-entity binds and remain typed,
      correct concrete ID classes, not merely values that compare or serialize.
- [x] Add service tests whose mocks/specs require `AgentId`, `SessionId`, and
      `TaskId`; prevent mocks typed as `Any` from hiding regressions.
- [x] Keep new bare UUID acceptance coverage only in dedicated boundary compatibility
      tests (`EntityId`/`EntityIdType`), and use typed IDs everywhere else.
- [x] Add negative tests for cross-entity misuse (`SessionId` passed as AgentId)
      at request, service, and persistence boundaries.
- [x] Add an architecture guard that fails on new domain annotations such as
      `agent_id: uuid.UUID`, legacy helper imports, or entity-prefix manipulation
      outside the ID module and approved adapters.
- [x] Replace stale Rust Session/Task fixtures and helper return types that still
      modeled entity identity as bare `Uuid`.
- [x] Remove obsolete Python `format_session_id`/`format_task_id` helpers and
      reject new core ID annotations using `uuid.UUID`, `UUID`, or `Any` across
      the entire Python application tree.
- [x] Rewrite stale Sandbox runtime tests so Redis/protobuf/provider boundaries assert bare UUIDs,
      while API schemas and error payloads assert canonical `sbx_<uuid>` values.

## P1 — Frontend Coordination

- [x] Introduce branded/template-literal types for `AgentId`, `SessionId`,
      `TaskId`, `TriggerId`, `EnvironmentId`, `SecretId`, `VaultId`, `CredentialId`, `SandboxId`,
      `MemoryStoreId`, `MemoryId`, `MemoryVersionId`, and all six Skill IDs with strict UUID-backed runtime parsers.
- [x] Extend branded/template-literal types to EventId and validate REST/SSE payloads at ingress.
- [x] Parse and validate API payload IDs once at the frontend API boundary;
      analytics, Trigger, Environment, Secret, Vault/Credential, storage-mount, Sandbox, Memory,
      Skill, File, SessionResource, and Event payloads are migrated.
- [x] Stop stripping `AgentId`, `SessionId`, `TaskId`, `TriggerId`, `EnvironmentId`, `SecretId`, `VaultId`, `CredentialId`, `SandboxId`, and all six Skill ID prefixes in
      `apiResourceId()` and migrated request builders. Canonical core IDs now pass
      unchanged through paths, query parameters, and bodies.
- [x] Rewrite `api-paths.test.ts` so it asserts canonical core-ID preservation
      while documenting the temporary legacy behavior for unmigrated entities.
- [x] Type Agent models, AgentVersion, SessionAgent, Trigger, analytics filters,
      mutation inputs, migrated response fields, Skill response/mutation chains, core route params, SSE inputs,
      and React Query keys at their boundaries.
- [x] Restrict prefix helpers to display formatting only for Agent/Session/Task/Trigger/Environment/Secret/Vault/Credential/Sandbox/Skill/File/SessionResource. They must not mutate
      core identity before API calls, equality checks, cache keys, or routing;
      unmigrated entity request paths still use the transitional helper.
- [x] Replace core fixtures such as `agent_a`, `agent_123`, `sess_123`, and stale
      Trigger IDs with canonical UUID-backed factories and add a regression guard.
- [x] Replace remaining Event fixtures; all audited entity fixtures are canonical UUID-backed IDs.
- [x] Add frontend contract tests proving canonical IDs survive response → URL →
      request round-trips without stripping or double-prefixing.
- [ ] Regenerate or validate frontend API types from the OpenAPI contract if
      code generation is adopted.

## P1 — Rust Orchestrator Scope

- [x] Make an explicit architecture decision: Rust kernel code adopts
      entity newtypes, or the orchestrator is formally treated as a raw-UUID
      boundary. SQLx/Serde remain transparent bare-UUID physical boundaries, while
      public formatting retains entity prefixes.
- [x] Add transparent `AgentId`, `SessionId`, `TaskId`, `EnvironmentId`, `VaultId`, `CredentialId`,
      `SandboxId`, `MemoryStoreId`, `MemoryId`, `MemoryVersionId`, `SkillId`, `SkillFileId`,
      `SkillSecurityScanId`, `SkillVersionId`, `SkillVersionFileId`, `SkillUsageId`, `FileId`,
      `SessionResourceId`, and `EventId` Rust newtypes with
      SQLx/Serde conversions and explicit public-prefix codecs.
- [x] Update Agent, Environment, Vault/Credential, Sandbox, Memory, Skill, File, and Event queries, scheduler, controllers, resolver, harness, providers,
      gRPC, Redis, and tests so core identities cannot be exchanged accidentally.
- [x] Migrate Session, Task, Environment, Vault/Credential, Sandbox, Memory, Skill, File, SessionResource, and Event query/kernel signatures from `Uuid` to their
      matching typed ID newtypes.
- [x] Remove `Deref<Uuid>` from Rust entity IDs so physical boundaries require explicit `.as_uuid()`.
- [x] Add unit tests for public-prefix validation, cross-entity rejection, and
      bare-UUID storage/wire round-trips.

## Completion Gates

- [x] Full-app mypy is audited with no typed-ID findings; the only remaining errors are four
      pre-existing nullable-user errors in `joysafeter_api/api/v1/auth.py`.
- [x] Backend validation covers 997 typed-fixture and contract tests: the prior 995-test full suite
      passed and both newly added architecture guards pass independently.
- [x] Backend sweep finds no migrated Agent/Session/Task/Trigger/Environment/Secret/Vault/Credential/Sandbox/Memory/Skill/File/SessionResource/Event `*_id` annotation
      using `uuid.UUID`, `UUID`, `str`, or `Any` in application/domain code.
- [x] Backend sweep finds no migrated legacy ID formatter/parser or manual
      Agent/Session/Task/Trigger/Environment/Secret/Vault/Credential/Sandbox/Memory/Skill/File/SessionResource/Event re-prefixing in application code.
- [x] `bun run type-check`, `bun run test`, and the production frontend build
      pass after the core branded-ID migration: 256 frontend tests passed.
- [x] Frontend API path/body tests assert canonical prefixed core IDs are
      preserved.
- [x] Rust tests pass after the chosen newtype/boundary decision is implemented:
      171 tests passed.
- [x] OpenAPI and architecture documentation describe canonical prefixed IDs for
      the migrated Agent/Session/Task/Trigger/Environment/Secret/Vault/Credential/Sandbox/Memory/Skill/File/SessionResource/Event boundaries.
