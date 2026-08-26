# Typed-ID Serialization Boundary Convergence Design

**Date:** 2026-08-25

**Status:** Implemented

## 1. Purpose

JoySafeter has completed most of the migration from stringly typed identifiers
to concrete `EntityId` subclasses in Python and native UUID storage in
PostgreSQL. The remaining response paths do not consistently preserve those
types until the public JSON boundary.

The visible failure is `GET /api/v1/auth/me` returning empty JSON objects for
user, organization, and project identifiers. The same causal pattern also
exists in login, registration, and organization-management responses, while
other endpoints currently avoid the failure through endpoint-local
`str(...)`, `model_dump(mode="json")`, or broad `default=str` behavior.

This design closes that debt as one boundary-convergence effort. It covers
paths that are already broken and paths that currently work only because of a
local compatibility conversion.

## 2. Classification

This is an architectural change because it establishes ownership of public ID
serialization across domain values, persistence adapters, application
results, REST DTOs, response middleware, error/audit payloads, WebSocket
notifications, SSE events, and frontend parsing.

It changes public response contracts from malformed or weakly specified values
to strict canonical prefixed IDs. No compatibility period is required because
the intended public contract already requires prefixed IDs and the frontend
already rejects malformed values.

## 3. Required Invariant

Every entity identifier has exactly one representation at each boundary:

| Boundary | Representation |
|---|---|
| PostgreSQL entity columns | Native UUID |
| SQLAlchemy model attributes | Concrete `EntityId` subtype |
| Python domain/application code | Concrete `EntityId` subtype |
| REST path/query/request DTO | Concrete `EntityId` subtype after validation |
| REST response DTO | Concrete `EntityId` subtype before serialization |
| Public JSON, SSE, WebSocket, audit JSON | Canonical prefixed string |
| Frontend transport input | Untrusted string validated into branded ID |
| Frontend application state | Entity-specific branded ID |

Conversions occur only at the owning physical or transport boundary:

- `EntityIdType` owns UUID-to-typed-ID persistence conversion.
- Pydantic response schemas own typed-ID-to-public-string REST conversion.
- Strict schema-less JSON adapters own conversion for explicitly untyped
  error, audit, and event payloads.
- Frontend parser functions own public-string-to-branded-ID conversion.

No intermediate application service or endpoint helper may convert entity IDs
to strings merely to make serialization succeed.

## 4. Root Cause

`EntityId.__get_pydantic_core_schema__` defines correct validation and JSON
serialization behavior. That serializer runs when Pydantic knows the concrete
field type.

Legacy endpoints construct nested Python dictionaries containing `EntityId`
instances and expose no FastAPI response model. FastAPI therefore processes
the dictionaries with `jsonable_encoder` without entity-specific field type
information. The custom value object is treated as an arbitrary object and is
encoded as `{}`.

The API response-wrapper middleware runs after FastAPI has produced the JSON
body. It receives the already corrupted `{}` value, parses that JSON, adds the
standard envelope, and cannot recover the lost identifier.

The existing tests missed this because they predominantly:

- call endpoint functions directly and inspect Python objects;
- inspect function annotations without making an ASGI request; or
- test frontend parsers only with already-canonical fixture strings.

Direct endpoint calls prove domain behavior, but they do not prove FastAPI
serialization behavior.

## 5. Confirmed Impact

The following response paths have the confirmed causal pattern:

- `GET /api/v1/auth/me`
  - `user.id`
  - `organization.id`
  - `project.id`
  - `project.org_id`
  - every `organizations[].id`
  - every `projects[].id` and `projects[].org_id`
- `POST /api/v1/auth/sign-in/email`
  - `data.user.id`
- `POST /api/v1/auth/sign-up/email`
  - `data.user.id`
- `POST /api/v1/organizations`
  - `id`
  - `project_id`
- `GET /api/v1/organizations/{organization_id}`
  - `id`
- `PUT /api/v1/organizations/{organization_id}`
  - `id`
- `POST /api/v1/organizations/{organization_id}/transfer-ownership`
  - `organization_id`
  - `previous_owner_user_id`
  - `new_owner_user_id`

The current audit also found the following debt indicators:

- 41 body-bearing JSON routes without a response model after excluding 204 and
  explicit `Response` routes;
- 32 manual pagination cursor `str(...)` conversions;
- 7 API-layer `model_dump(mode="json")` calls;
- 6 production `json.dumps(..., default=str)` uses; and
- 2 targeted `jsonable_encoder(..., custom_encoder={EntityId: str})` uses.

These counts are audit inputs, not a requirement to mechanically remove every
occurrence. Each occurrence must be classified by boundary ownership before it
is retained or removed.

## 6. Architecture

### 6.1 Entity-ID value objects

`app.joysafeter_shared.ids` remains the single source of truth for entity
prefixes, value equality, parsing, and Pydantic integration.

`EntityId` must not:

- inherit from `str`;
- implement a permissive generic JSON fallback;
- accept bare UUID strings at public boundaries;
- accept another entity's prefixed ID; or
- expose compatibility aliases for historical string formats.

Changing `EntityId` into a transport primitive would mix domain identity with
JSON concerns and make invalid cross-entity values easier to propagate.

### 6.2 Persistence adapter

`app.joysafeter_shared.sqlalchemy_ids.EntityIdType` remains the only normal
conversion point between database UUID columns and Python typed IDs.

Application and API code must not use `.uuid`, `from_uuid`, or `as_uuid` unless
interacting with a documented physical protocol that stores bare UUIDs.

### 6.3 Application results

Application/domain services return typed results, not public JSON dictionaries.

Authentication token issuance will return a typed result containing:

- the authenticated `AuthUser` or a typed user projection;
- access, refresh, and CSRF tokens;
- access and refresh expiration timestamps; and
- token type.

The API layer maps that result into its public response DTO and cookie values.
The existing `_build_jwt_login_response` transport dictionary is removed.

This keeps camel-case compatibility fields, response messages, and cookie
behavior in the API transport owner instead of the domain service.

### 6.4 REST response DTOs

Every body-bearing JSON route must provide a concrete Pydantic response model,
either through its return annotation or the router's `response_model`.

Exceptions are limited to:

- HTTP 204 routes with no body;
- streaming/SSE responses;
- file downloads and redirects returning an explicit Starlette `Response`;
- low-level health responses that intentionally construct `JSONResponse` from
  JSON primitives; and
- explicitly reviewed schema-less protocol boundaries.

All response fields representing entity IDs use their concrete `EntityId`
subtype. Nested user, organization, project, membership, and pagination
objects must also be typed; `dict[str, object]` and `dict[str, Any]` are not
acceptable substitutes for known response structure.

`GET /auth/me` receives nested DTOs for:

- current user;
- organization summary;
- project summary;
- active project context;
- organization list entries; and
- project list entries.

The existing `AuthMeResponse`, whose flat fields no longer match the endpoint,
is replaced rather than retained as an alias.

### 6.5 Pagination

The shared cursor response becomes generic over both item and identifier type.
Conceptually:

```python
ItemT = TypeVar("ItemT")
CursorIdT = TypeVar("CursorIdT")

class CursorPaginatedResponse(BaseModel, Generic[ItemT, CursorIdT]):
    data: list[ItemT]
    has_more: bool
    first_id: CursorIdT | None = None
    last_id: CursorIdT | None = None
```

Each route supplies the matching entity ID type. This removes endpoint-local
cursor stringification and lets Pydantic serialize the cursor through the same
contract as item IDs.

### 6.6 Standard response envelope

The existing API middleware may continue to wrap successful inner responses,
but it only operates on JSON that FastAPI has already serialized.

The middleware must:

- preserve status, headers, and repeated `Set-Cookie` values;
- preserve pagination flattening while that public shape remains supported;
- use strict `json.dumps` without `default=str`; and
- never attempt to recover or convert domain objects.

Authentication endpoints that return a pre-built success envelope use typed
`ApiResponse[T]` instances rather than `success_response()` dictionaries.

If replacing all callers leaves `success_response()` or
`paginated_response()` unused, those functions are deleted. No deprecated
wrapper remains.

### 6.7 Schema-less JSON boundaries

Error details, audit details, event payloads, and notification payloads are
partly schema-less by design. They cannot rely on response DTO field types.

These boundaries use one strict, boundary-owned normalization mechanism with
an explicit allowlist. It may accept:

- JSON primitives and `None`;
- lists, tuples, and mappings containing supported values;
- concrete `EntityId` instances, converted with `str`;
- dates and datetimes, converted with ISO 8601; and
- enums, converted to their declared value when that value is JSON-safe.

Unsupported arbitrary objects raise a boundary error. They must not be silently
converted with `default=str`.

The strict normalizer is used only by reviewed schema-less infrastructure
adapters. REST endpoint code must not call it as an alternative to defining a
response DTO.

Targeted existing encoders in exception and audit handling remain until this
strict adapter replaces them. They are not removed before equivalent
fail-closed behavior exists.

### 6.8 Frontend boundary

Frontend response payload types continue to treat network values as untrusted
strings. Existing parser functions validate prefixes and return branded IDs.

The backend change does not weaken frontend validation. The frontend remains a
second independent contract check and must continue rejecting:

- `{}` or other non-string values;
- bare UUID strings; and
- IDs with another entity's prefix.

Persisted frontend state is not migrated or repaired through prefix inference.

## 7. Obsolete Code Removal

The implementation removes obsolete code only after replacement tests pass:

- the stale flat `AuthMeResponse` definition;
- `_project_context_payload` and `_active_project_payload` dictionary builders,
  replaced with typed DTO constructors;
- `_build_jwt_login_response` and domain-layer public response dictionaries;
- endpoint-local ID `str(...)` used solely for REST serialization;
- endpoint-local DTO `model_dump(mode="json")` used solely to make raw response
  dictionaries serializable;
- analytics field serializers whose only purpose is forcing IDs to strings in
  Python-mode `model_dump()`;
- `default=str` from the API response wrapper;
- broad `default=str` from WebSocket/event publishers after strict payload
  normalization is in place;
- duplicate organization request/response definitions; and
- the duplicate `/auth/organizations` route if repository usage, tests, and
  published documentation confirm `/organizations` is the sole supported
  endpoint.

There will be no compatibility import, compatibility route, alias schema,
dual serializer, or fallback conversion left behind.

Logging, SQL parameters, Redis channel names that intentionally use physical
UUIDs, and explicitly string-valued external protocols are reviewed separately
and retained when the conversion belongs to that boundary.

## 8. Error and Failure Behavior

- A valid typed ID in a typed REST response serializes to its canonical prefix.
- A bare UUID or wrong-prefix ID entering a request fails validation before
  repository access.
- An endpoint returning an unsupported arbitrary object fails during testing
  or response serialization; it is not converted to a misleading string.
- Schema-less adapters report the boundary and unsupported value type without
  including secrets or raw credential material.
- The response wrapper never changes a successful field value beyond adding
  the documented envelope.
- No fallback emits `{}`, a bare UUID, or a cross-entity prefix.

## 9. Testing Strategy

### 9.1 Core serialization tests

Prove the intended Pydantic behavior:

- a concrete typed field serializes to a canonical prefixed string;
- a nested typed DTO serializes correctly;
- a raw dictionary containing `EntityId` demonstrates the historical `{}`
  failure and is never used as the production solution; and
- fields declared as `Any` reject unsupported embedded IDs unless they pass
  through an approved schema-less boundary.

### 9.2 REST regression tests

Use FastAPI `TestClient` or ASGI HTTP clients, not direct endpoint calls, for:

- sign-in;
- sign-up;
- current auth context;
- context switching;
- organization create/get/update/transfer;
- representative lists for every pagination ID family; and
- representative nested resources containing multiple entity ID types.

Assertions cover:

- canonical prefix and UUID value;
- nested and list fields;
- nullable IDs;
- empty pages;
- no `{}` values;
- no bare UUID strings;
- no wrong-prefix values; and
- unchanged envelope and cookie behavior.

### 9.3 Architecture tests

Add repository-level tests that fail when:

- a body-bearing JSON route lacks a response model without being allowlisted;
- a REST endpoint performs an ID-only `str(...)` conversion;
- a REST endpoint dumps a DTO to JSON mode instead of returning the DTO;
- API response middleware uses `default=str`;
- a public response schema declares a known entity-ID field as plain `str` or
  `Any`; or
- a removed compatibility helper, filename, directory, route, or schema name
  is reintroduced.

Allowlist entries must name the physical or schema-less boundary and explain
why it cannot use a typed DTO.

### 9.4 Schema-less boundary tests

For errors, audit, WebSocket, and session events:

- supported entity IDs become canonical strings recursively;
- dates, enums, lists, and mappings serialize deterministically;
- unsupported objects fail closed;
- secret material remains absent from logs and audit payloads; and
- published event shapes remain compatible with SSE and frontend consumers.

### 9.5 Frontend tests

Retain and extend parser tests to prove that real backend-shaped fixtures:

- accept all canonical auth and organization IDs;
- reject `{}` values;
- reject bare UUIDs;
- reject cross-entity prefixes; and
- populate project and organization stores without fallback conversion.

## 10. Implementation Decomposition

The work is split into two independently testable tracks under the same
invariant.

### Track A: REST response-contract closure

1. Add ASGI regression tests for the confirmed broken endpoints.
2. Introduce typed authentication and tenant response DTOs.
3. Replace application-service login dictionaries with typed results.
4. Convert auth and organization endpoints to typed DTO returns.
5. Generalize cursor pagination over the cursor ID type.
6. Convert all paginated REST routes and remove manual cursor conversions.
7. Add the response-model architecture gate.
8. Remove obsolete helpers, duplicate schemas, and confirmed unused routes.
9. Run backend and frontend REST contract verification.

### Track B: Schema-less JSON boundary hardening

1. Add fail-closed normalization tests.
2. Introduce the strict schema-less boundary normalizer.
3. Migrate error and audit payload encoding.
4. Migrate WebSocket notification serialization.
5. Migrate session realtime/SSE event serialization.
6. Remove broad `default=str` usage covered by the adapter.
7. Audit remaining explicit string conversions by physical boundary.
8. Run event, worker, WebSocket, SSE, and security verification.

Track A resolves the current production-visible defect. Track B removes the
remaining permissive serialization debt without coupling event-protocol risk to
the REST fix.

## 11. Rejected Alternatives

### Global `default=str`

Rejected because it silently converts unsupported objects, masks missing
schemas, and can leak unstable implementation representations.

### Endpoint-local `str(id)`

Rejected because it duplicates transport responsibility and allows callers to
forget individual nested fields.

### Endpoint-local `model_dump(mode="json")`

Rejected because it collapses DTOs into dictionaries before FastAPI validates
the declared response contract and encourages mixed response styles.

### Make `EntityId` inherit from `str`

Rejected because it turns a domain identity value into a transport primitive,
weakens entity-type separation, and complicates native UUID persistence.

### Custom FastAPI internals or monkey-patching `jsonable_encoder`

Rejected because it depends on framework internals, applies globally to
unknown objects, and hides routes that lack explicit response contracts.

### Retain dual old/new routes or serializers

Rejected because the intended contract is already canonical prefixed IDs.
Compatibility paths would preserve the historical debt rather than provide a
needed migration window.

## 12. Completion Criteria

The convergence is complete only when all of the following are proven from the
current worktree:

- confirmed affected endpoints return canonical prefixed IDs through ASGI;
- all body-bearing REST JSON routes satisfy the response-model rule or a
  reviewed allowlist;
- pagination cursors carry concrete ID types without endpoint string bridges;
- domain/application services do not construct public auth response JSON;
- broad production `default=str` uses in the covered boundaries are removed;
- schema-less boundaries fail closed for unsupported objects;
- obsolete helpers, duplicate schemas/routes, compatibility names, filenames,
  and directories are absent;
- backend targeted and broader suites pass;
- frontend parser/store tests and type checking pass;
- worker/event/WebSocket tests pass for Track B;
- documentation contract checks pass; and
- final repository scans find no unreviewed ID serialization bridge.
