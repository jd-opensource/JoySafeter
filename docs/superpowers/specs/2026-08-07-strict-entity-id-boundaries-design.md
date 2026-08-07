# Strict Entity ID Boundaries — Design Spec

**Date:** 2026-08-07
**Status:** Approved
**Supersedes:** The bare UUID string compatibility described in `2026-08-06-typed-entity-id-value-objects-design.md`
**Scope:** Backend Python, Rust orchestrator, frontend managed UI, persistence adapters, Redis, and cross-language protocols

## Goal

JoySafeter has not been released and its databases may be rebuilt. Remove all
historical bare UUID string compatibility instead of preserving or expanding
regex-based normalization. Every entity identifier must have one canonical
representation at each boundary.

## Canonical Representations

| Boundary | Canonical representation | Rule |
|---|---|---|
| Public API paths, queries, request JSON, response JSON | Typed prefixed string such as `task_<uuid>` | Bare UUID strings and wrong prefixes are rejected |
| Frontend application state and API parser output | Typed prefixed string | No prefix stripping for equality or lookup |
| Python domain and ORM attributes | Concrete `EntityId` subtype | Cross-entity construction is rejected |
| Rust domain code | Concrete typed ID wrapper | Public strings use strict `from_public`; storage UUIDs use `from_uuid` |
| PostgreSQL UUID columns | Native UUID | Conversion occurs only in the SQLAlchemy/sqlx adapter |
| JSON/JSONB persisted entity references | Typed prefixed string | No dual-format reads or queries |
| Redis and cross-language protocol fields documented as physical UUIDs | Bare UUID string | Conversion is explicit at the producer and consumer boundary |

## Strict Construction Rules

`EntityId` construction must distinguish semantic input from physical input:

- `EntityId.from_public(value: str)` accepts only the class's canonical prefix.
- `EntityId.from_uuid(value: uuid.UUID)` is the only named conversion from a
  physical UUID.
- Direct construction may accept the same concrete ID type and native
  `uuid.UUID`, but must reject every string, including a correctly prefixed
  public string and a bare UUID string. This keeps string parsing visible at
  call sites.
- Pydantic validation treats strings as public values and therefore requires
  the canonical prefix. Native UUID values are allowed only for trusted
  Python-side validation/ORM hydration, not JSON input.
- `as_uuid` accepts only native UUIDs or typed IDs; it never parses strings.

Rust wrappers follow the same semantic split: `from_public` for prefixed
external strings and `from_uuid`/`as_uuid` for physical storage and protocol
boundaries. General parsing must not silently accept both forms.

## Compatibility Code To Remove

The audit must remove or replace all behavior in these categories:

1. `removeprefix`, optional-prefix regexes, or `startswith` branches that make
   an entity prefix optional.
2. Helpers that accept both `prefix_<uuid>` and `<uuid>` for the same public
   field.
3. JSONB queries that search both prefixed and bare forms.
4. Frontend comparisons that call `stripIdPrefix` on both operands.
5. Broad string constructors such as `TaskId(raw_string)` where the caller has
   not declared whether `raw_string` is public or physical.
6. Tests and documentation that advertise bare UUID strings as supported API
   input.

This is a semantic audit, not a larger regex replacement. Each match must be
classified by boundary before modification.

## Allowed Bare UUID Boundaries

Bare UUIDs remain valid only where the contract is physical rather than
public. Every retained occurrence must have a local comment or type signature
that identifies the boundary and must use an explicit adapter.

Expected categories include:

- PostgreSQL UUID bind/result conversion.
- Advisory-lock keys derived from physical UUIDs.
- Redis queue/channel payloads consumed by code that parses a native UUID.
- Runner/orchestrator protocol fields whose schema explicitly defines a bare
  UUID.
- OpenTelemetry trace/observation storage that is not an entity public ID.
- Third-party APIs whose documented identifier format is a UUID rather than a
  JoySafeter entity ID.

A UUID-backed value is not automatically an exception. If it identifies a
JoySafeter entity in a public or persisted JSON contract, it uses its typed
prefix.

## Persistence And Reset Policy

- No data migration or compatibility read path is required.
- Development and test databases are rebuilt from the canonical schema.
- Alembic history must describe only the canonical format for seeded or JSON
  values; UUID column types remain unchanged.
- Fixtures, snapshots, and seed data are updated rather than normalized at
  runtime.

## Error Contract

Invalid public IDs continue through the existing structured validation error
path. The cleanup must preserve field-specific error codes and metadata while
making bare UUID strings fail consistently in paths, queries, and JSON bodies.

Wrong entity prefixes must fail rather than being stripped and re-labeled.

## Verification Strategy

Tests must prove both sides of the boundary:

- Public API and Pydantic tests reject bare UUID strings for every typed ID.
- Direct constructors reject all strings; `from_public` and `from_uuid` cover
  their distinct valid inputs.
- Frontend parsers and lookup paths reject or fail to match bare UUIDs.
- JSONB persistence and queries operate on one canonical prefixed form.
- Explicit Redis, database, and protocol adapter tests still emit/consume bare
  UUIDs where required.
- Repository searches for optional-prefix patterns are reviewed manually; zero
  unclassified compatibility points remain.

## Success Criteria

1. There is no public or persisted-JSON path that accepts a bare entity UUID.
2. There is no generic entity-ID string parser that accepts both forms.
3. Every retained bare UUID conversion is an explicit physical-boundary
   adapter with test coverage.
4. Backend, Rust, and frontend targeted suites pass after database reset.
5. The final audit lists retained physical boundaries and removed compatibility
   points; it does not introduce a broader regex normalization layer.
