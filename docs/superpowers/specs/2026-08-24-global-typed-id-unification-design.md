# Global Typed ID Unification Design

**Date:** 2026-08-24
**Status:** Implemented
**Scope:** Python backend, Rust orchestrator, sandbox runner, CLI, frontend, persisted JSON/JSONB, tests, and normative documentation

## Goal

Make every UUID-backed JoySafeter entity identifier use one semantic type per
language, one canonical public representation, and one explicit lifecycle
owner. Remove historical optional-prefix parsing, duplicate ID types, generic
`Any`/`object` ID channels, legacy credential-reference field aliases, and
ad-hoc prefix conversion helpers.

The result is not “fewer search matches.” The result is an enforceable
invariant: every conversion is owned by a documented boundary and every ID is
created by the component that creates the corresponding entity or event.

## Current Problems

### Duplicate Python identity systems

`backend/app/joysafeter_shared/ids.py` defines the authoritative UUID-backed
`EntityId` value objects, while
`backend/app/joysafeter_domain/credentials/types.py` independently defines
`CredentialId` and `CredentialGroupId` as `NewType(..., str)`.

This creates two semantically different Python types for the same public IDs.
Infrastructure compensates with aliases and conversion helpers such as
`DomainCredentialId`, `SqlCredentialId`, `_shared_credential_id`, and
`_sql_credential_id`. Those bridges make invalid states representable and hide
which boundary parsed the identifier.

### Weakly typed application ports

Credential application ports and services use `Any` or `object` for entity IDs,
including group, agent, environment, session, and task identifiers. This moves
identity validation out of the owning boundary and makes call chains depend on
runtime convention instead of types.

### Runner accepts both public and physical forms

`sandbox-runner/crates/joysafeter-types` stores public entity IDs as raw
`uuid::Uuid` values with per-file serializers and parsers. Parsers use
`strip_prefix(...).unwrap_or(...)`, so both canonical prefixed strings and bare
UUID strings are accepted.

The CLI repeats this behavior with `normalize_resource_id` and direct prefix
stripping before constructing REST paths. This contradicts the public REST
contract and can send an invalid bare UUID to strict backend routes.

### Legacy credential-reference aliases remain executable

Runtime readers still accept fields such as `secret_ref`, `secret_refs`,
`service_credential_id`, and `vault_ids` alongside the canonical
`model_credential_id`, `environment_credential_ids`, egress
`credential_ref`, and `credential_group_ids` fields.

Because these aliases remain in Python, Rust, frontend parsers, persisted
snapshots, and CLI manifests, the system still has multiple identity contracts.

### ID creation is frequently persistence-triggered

Most Python ORM models use `default=<EntityId>.new`. SQLAlchemy therefore
creates identity during flush rather than when the owning use case creates the
entity. The in-memory entity can temporarily have no stable ID, and ownership
of identity creation is obscured.

### Architecture guards are incomplete

The current backend guard verifies many Python and orchestrator call sites but
does not scan `sandbox-runner`, prohibit duplicate semantic ID definitions, or
prove that entity creation happens at the owning lifecycle boundary. Existing
tests therefore pass while compatibility behavior remains.

## Required Invariants

### Canonical representation by boundary

| Boundary | Representation |
|---|---|
| REST paths, queries, request JSON, response JSON, SSE, persisted JSON/JSONB | Strict prefixed ID, for example `task_<uuid>` |
| Python application and domain | Concrete `EntityId` subtype |
| Rust application and domain | Concrete typed ID newtype |
| Frontend state | Branded prefixed ID |
| PostgreSQL UUID columns | Native UUID through the SQL adapter only |
| Redis/protobuf fields explicitly defined as physical UUIDs | Bare UUID through a named adapter at producer and consumer |
| Infrastructure resource names and object-store keys | Bare UUID only where the physical naming contract requires it |

No public or persisted reader may accept both prefixed and bare UUID forms.

### Identity lifecycle ownership

| Entity | ID creation owner |
|---|---|
| Agent | Agent create command/application service |
| Session | Session creation/snapshot application service |
| Task | Task submission or trigger-fire use case |
| Environment | Environment creation service |
| Credential and credential group | Credential application service before repository insertion |
| Memory store, memory, and memory version | Memory service operation creating the record |
| Skill and child skill records | Skill service operation creating each record |
| File and session resource | File/session-resource application service before external side effects |
| Storage volume, grants, and mount audit | Storage service operation creating the record |
| Sandbox | Orchestrator sandbox lifecycle owner |
| Event | Event producer before enqueue/persist |

ORM column defaults must not be the authoritative creation mechanism for
UUID-backed entity IDs. Constructors receive an explicit typed ID. Database
hydration converts native UUIDs back to the matching type.

The frontend, CLI, runner, and consumers never mint server-owned entity IDs.
Request/idempotency/telemetry UUIDs are separate non-entity identities and are
not converted into entity IDs.

## Design

### 1. Python canonical value objects and SQL adapter

Keep `backend/app/joysafeter_shared/ids.py` as the single Python entity-ID
module. Remove its top-level SQLAlchemy dependency and keep public parsing,
native UUID construction, equality, hashing, Pydantic integration, and the
registered prefix inventory there.

Move `EntityIdType` into
`backend/app/joysafeter_shared/sqlalchemy_ids.py`. ORM model modules import
value objects from `ids.py` and the persistence adapter from
`sqlalchemy_ids.py`.

The credential domain may import exactly the dependency-light shared ID module.
Its architecture guard continues to forbid API, application, infrastructure,
SQLAlchemy, Redis, and HTTP dependencies.

Delete the duplicate `CredentialId` and `CredentialGroupId` `NewType`
definitions and their `make_*` parsing functions. `ProjectId` remains a text
newtype because organization/project/auth IDs are externally managed text IDs,
not members of the UUID-backed entity inventory. `ReferenceSurfaceId` and
`ReferenceScannerId` also remain symbolic identifiers rather than entity IDs.

### 2. Strongly typed Python ports

Replace credential-domain and application `Any`/`object` ID positions with the
actual types:

- `CredentialGroupId` for group operations;
- `AgentId` and `EnvironmentId` for snapshot ownership;
- `SessionId` and `TaskId` for credential material access and audit context;
- `SandboxId` and `SessionId` collections for runtime impact reporting.

Serialization to strings remains only in audit/log/error/JSON output code.
Repository predicates receive typed IDs and rely on `EntityIdType` for SQL UUID
binding.

### 3. Explicit Python entity creation

Every production constructor for a UUID-backed entity supplies `id=<Type>.new()`
from the service or application use case that owns creation. ORM defaults are
removed after all creation paths and tests are migrated.

Creation paths are reviewed individually. A type is not inserted mechanically:
the caller must be classified as aggregate creator, child-record creator,
event producer, persistence hydrator, or test fixture.

### 4. Shared Rust typed-ID crate

Create `shared/rust/joysafeter-entity-id` as the single Rust implementation for
entity ID newtypes used by both Rust workspaces. The crate provides:

- strict `from_public` and prefixed serde;
- explicit `from_uuid` and `as_uuid`;
- no `Deref<Uuid>` and no optional-prefix parser;
- optional SQLx support for the orchestrator;
- the authoritative Rust prefix registry and tests.

The orchestrator removes its local implementation in
`backend/app/joysafeter_orchestrator_rs/src/ids.rs` or reduces that module to
explicit re-exports. `sandbox-runner/crates/joysafeter-types` replaces raw UUID
fields representing public entity IDs with shared newtypes.

Bare UUID protobuf fields remain unchanged. Conversion occurs only in gRPC
construction/decoding functions and is covered by contract tests.

### 5. Strict runner and CLI boundaries

Remove runner serializers/parsers that manually add or optionally strip
prefixes. Serde on typed IDs becomes the only JSON codec.

Remove CLI `normalize_resource_id` helpers and direct `agent_` stripping. REST
paths preserve canonical IDs. CLI arguments representing entity IDs are parsed
into the matching typed ID before requests are sent.

The obsolete Secret/Vault CLI surface is removed rather than adapted to
nonexistent routes. Current CLI credential operations use `/credentials` and
`/credential-groups` with `CredentialId` and `CredentialGroupId`.

### 6. Remove persisted alias compatibility

Add a fail-closed data migration that rewrites legacy persisted references to
canonical keys and rejects conflicts or malformed IDs:

- `secret_ref` → `model_credential_id`;
- `secret_refs` → `environment_credential_ids`;
- root `service_credential_id` → `environment_credential_ids` where the old
  schema represented a direct environment credential;
- `vault_ids` → `credential_group_ids`;
- egress `service_credential_id` → `credential_ref`.

The migration must preserve canonical `cred_`/`credgrp_` values, deduplicate
lists deterministically, and fail when old and new keys disagree. After the
migration, Python, Rust, frontend, and CLI readers accept only canonical keys.

No runtime dual-read, fallback, or compatibility enum remains.

### 7. Repository-wide enforcement

Extend architecture tests to prove:

- the Python entity inventory has no duplicate semantic definitions;
- no entity-ID annotation uses `str`, `Any`, `object`, or raw UUID outside an
  explicitly reviewed physical boundary;
- no optional-prefix parser or generic prefix-removal helper exists in
  production Python, Rust, frontend, or CLI code;
- every retained `as_uuid`/`from_uuid` conversion is allowlisted by boundary,
  file, function, and count;
- each ORM entity class lacks an ID-generation default and each production
  creation path supplies the correct ID type;
- Python, Rust, and frontend prefix inventories agree;
- legacy credential-reference keys and old Secret/Vault routes do not occur in
  executable production code or normative API documentation.

## Failure Behavior

- Bare UUID at a public boundary: reject with the existing invalid-ID contract.
- Wrong entity prefix: reject before repository or runtime access.
- Legacy persisted key after migration: reject as unsupported/corrupt data.
- Conflicting old/new keys during migration: abort migration with identifying
  row coordinates but no credential material.
- Wrong typed ID passed to SQL: `EntityIdType` raises `TypeError`.
- Missing explicit ID at entity construction: test/typing failure before flush.

## Primary Files and Directories

### Python

- `backend/app/joysafeter_shared/ids.py`
- `backend/app/joysafeter_shared/sqlalchemy_ids.py` (new)
- `backend/app/joysafeter_domain/credentials/types.py`
- `backend/app/joysafeter_domain/credentials/`
- `backend/app/joysafeter_application/credentials/`
- `backend/app/joysafeter_application/environments/credential_service.py`
- `backend/app/joysafeter_infrastructure/credentials/`
- `backend/app/joysafeter_infrastructure/agents/credential_binding_adapter.py`
- `backend/app/joysafeter_domain/models/`
- entity-creating services under `backend/app/joysafeter_application/` and
  `backend/app/joysafeter_domain/services/`
- `backend/alembic/versions/` (new canonical-reference migration)

### Rust

- `shared/rust/joysafeter-entity-id/` (new)
- `backend/app/joysafeter_orchestrator_rs/Cargo.toml`
- `backend/app/joysafeter_orchestrator_rs/src/ids.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/credentials/reference.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/run_spec.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs`
- `backend/app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs`
- `sandbox-runner/Cargo.toml`
- `sandbox-runner/crates/joysafeter-types/`
- `sandbox-runner/crates/joysafeter-ctl/`

### Frontend and documentation

- `frontend/types/entity-id.ts`
- `frontend/types/managed.ts`
- `frontend/lib/managed/credential-reference-contract.ts`
- `frontend/lib/managed/environment-response-parsers.ts`
- affected frontend callers and tests
- `backend/tests/test_typed_id_architecture.py`
- `backend/tests/test_credential_domain_architecture.py`
- `frontend/types/entity-id-architecture.test.ts`
- `scripts/check_documentation_contracts.py`
- `docs/ARCHITECTURE.md`
- `docs/ARCHITECTURE_CN.md`
- `docs/api/openapi.md`

## Verification Strategy

1. Add failing architecture tests for each confirmed gap before production
   changes.
2. Add focused unit tests for strict codecs and wrong-prefix/bare-UUID rejection.
3. Add migration tests covering canonical-only, legacy-only, equal dual-key,
   conflicting dual-key, malformed ID, and list deduplication cases.
4. Run focused Python credential and entity-ID tests.
5. Run focused orchestrator and sandbox-runner tests.
6. Run frontend parser, architecture, and type-check tests.
7. Run the broader commands documented in `DEVELOPMENT.md`.
8. Run final repository searches and architecture guards; a green test suite is
   not sufficient if the scans do not cover every source root.

## Non-Goals

- Organization, project, user, provider, protocol, request, idempotency, trace,
  and third-party IDs are not automatically converted into UUID-backed entity
  IDs. Each remains governed by its own lifecycle and external contract.
- Physical PostgreSQL column types and protobuf field schemas are not changed
  merely to avoid explicit conversion.
- Historical planning/evidence documents are not rewritten; normative current
  documentation and executable code are updated.
