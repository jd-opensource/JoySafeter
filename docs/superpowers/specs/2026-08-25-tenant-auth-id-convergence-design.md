# Tenant and Authentication ID Convergence Design

**Date:** 2026-08-25
**Status:** Implemented
**Scope:** Python backend, PostgreSQL schema, Rust orchestrator, frontend, authentication tokens, persisted audit records, telemetry boundaries, filenames, directories, tests, and normative documentation

## Goal

Complete the repository-wide typed-ID convergence by bringing user,
organization, project, membership, OAuth-account, authentication-session,
audit, and sandbox-network-policy identities under the same rules already used
for the core JoySafeter entities.

Every change must be justified by the identity's semantic owner. This is not a
text replacement exercise: third-party IDs, runtime provider IDs, idempotency
keys, trace IDs, and polymorphic references remain distinct contracts.

## Root Cause

The earlier global typed-ID design explicitly excluded organization, project,
and user IDs. Those IDs are nevertheless UUID-backed JoySafeter entities that
cross REST, JWT, frontend, PostgreSQL, Redis, and Rust boundaries. The
exclusion left duplicate `ProjectId` wrappers, text PK/FK columns, untyped auth
context fields, ORM-generated identities, consumer-side event-ID fallback,
and SQL-generated policy IDs.

A repository audit also found a disconnected Observation persistence prototype:
its creation entrypoint and database migrations had already been removed, while
the ORM models, processors, placeholder API, frontend waterfall, and architecture
claims remained. Those files do not define active entities and are removed rather
than assigned new ID types. Request-level OTel trace IDs remain diagnostic values.

## Canonical Identity Inventory

### Public entity IDs

| Entity | Type | Public prefix | Lifecycle owner |
|---|---|---|---|
| User | `UserId` | `user_` | Registration or federated-account application flow |
| Organization | `OrganizationId` | `org_` | `OrganizationService` create operation |
| Organization membership | `OrganizationMemberId` | `orgmem_` | Organization membership create operation |
| Project | `ProjectId` | `proj_` | `ProjectService` or organization bootstrap operation |
| Project membership | `ProjectMemberId` | `projmem_` | Project membership grant operation |
| OAuth account binding | `OAuthAccountId` | `oauthacct_` | Federation account gateway when creating a binding |
| Authentication session | `AuthSessionId` | `authsess_` | `AuthService` before session persistence |

### Internal record IDs

| Record | Type | Public prefix | Lifecycle owner |
|---|---|---|---|
| Credential access audit | `CredentialAccessAuditId` | `credaudit_` | Credential access audit event producer |
| Security audit | `SecurityAuditId` | `secaudit_` | Security audit event producer |
| Sandbox network policy | `SandboxNetworkPolicyId` | `sbxnetpol_` | Orchestrator policy-state producer |

Internal IDs use the same typed value-object implementation and native UUID
storage, but are not added to frontend types unless an API actually exposes
them.

## Explicit Non-Entity IDs

The following remain separate semantic strings or dedicated value objects:

- OAuth provider subject (`provider_account_id`)
- Stripe customer ID
- Docker/Kubernetes/provider sandbox external ID
- Harness session ID
- Orchestrator instance ID
- Request, trace, correlation, and idempotency IDs
- Federation provider and protocol IDs
- Polymorphic `principal_id`, `consumer_id`, and audit `target_id`

Polymorphic IDs must be validated together with their discriminator. They must
not be incorrectly assigned one concrete entity-ID type.

## Boundary Representations

| Boundary | Representation |
|---|---|
| REST paths, request/response JSON, JWT, SSE, frontend state | Strict prefixed ID |
| Python domain/application | Concrete `EntityId` subtype |
| Rust domain/application | Concrete typed-ID newtype |
| PostgreSQL PK/FK and monomorphic snapshot columns | Native UUID |
| Polymorphic audit references | Discriminator plus canonical prefixed string |
| Third-party/runtime identifiers | Their own validated string contract |

No runtime reader accepts both bare UUID and prefixed forms.

## Lifecycle Rules

1. The application operation that decides a durable entity or event exists
   creates its ID before persistence or external side effects.
2. ORM defaults, repository implementations, SQL functions, database defaults,
   and consumers do not create entity identity.
3. Event producers create `EventId`; Worker consumers reject missing or invalid
   IDs and route poison messages through the existing failure path.
4. Audit producers create audit IDs before calling adapters.
5. The Rust network-policy operation creates `SandboxNetworkPolicyId` before
   executing SQL and binds it explicitly.

## Database Migration

The migration is a coordinated cutover with no runtime compatibility phase.

1. Preflight every affected PK, FK, and monomorphic snapshot column. Values
   must be `NULL` or valid bare UUID text. Unexpected values abort with table,
   column, and count information.
2. Verify referential integrity and the API-key composite project/org invariant.
3. Drop dependent foreign keys, composite constraints, and indexes as required.
4. Convert user, organization, project, membership, OAuth-account, auth-session,
   audit, policy, and all referencing columns with `USING col::uuid`.
5. Recreate foreign keys, unique constraints, composite constraints, and indexes.
6. Delete all authentication-session rows so old refresh sessions cannot mint
   new tokens. Existing access and CSRF JWTs fail strict prefixed-ID parsing.
7. Downgrade may cast UUID columns back to text, but does not restore deleted
   sessions or old-token validity.

## Authentication Contract

JWT claims use canonical public IDs:

- `sub`: `UserId`
- `org_id`: `OrganizationId`
- `project_id`: `ProjectId`

`JoySafeterAuthContext` carries those concrete types. Authentication and API
boundaries parse once and reject bare UUIDs, wrong prefixes, and malformed
values before repository access.

Frontend persisted auth/project state is version-bumped and invalidated rather
than migrated through a dual-format reader.

## Removing False Identity and Compatibility

The environment credential comparison must not construct the fake project ID
`environment-impact-surface`. It compares a project-free
`CredentialBindingFingerprint` value object containing only binding identity
and usage semantics.

The following are removed:

- Python credential-domain `NewType("ProjectId", str)` and helper bridges
- Rust credential-kernel local `ProjectId(String)`
- Worker event-ID fallback generation
- SQL `gen_random_uuid()` for sandbox network-policy records
- ORM `default` functions for the newly typed entities
- Auth/JWT/frontend `str` or `string` identity channels

## Files and Directories

- `backend/app/joysafeter_shared/ids.py` remains the Python value-object source.
- `backend/app/joysafeter_shared/sqlalchemy_ids.py` remains the Python SQL adapter.
- `shared/rust/joysafeter-entity-id/` remains the Rust source of truth.
- `backend/app/joysafeter_orchestrator_rs/src/ids.rs` remains a valid re-export facade.
- `frontend/types/entity-id.ts` remains the frontend source of truth.
- `frontend/lib/managed/id.ts` is renamed to
  `frontend/lib/managed/entity-id-display.ts`; the bare-UUID extraction export
  is removed because the frontend only needs formatted display.
- Removed application `secrets/` and `vaults/` routes/directories stay deleted.
- Historical Alembic migration filenames remain immutable.
- Helm `secret.yaml` files remain because they represent Kubernetes Secrets,
  not the removed business Secret entity.
- Generated caches are excluded from architectural scans and may be deleted as
  workspace cleanup, but do not define source contracts.

## Tests and Completion Evidence

Completion requires current evidence for all of the following:

1. Shared prefix inventories agree across Python, Rust, and frontend.
2. Every known monomorphic identity field has the correct concrete type.
3. Every production constructor supplies an explicit correctly typed ID.
4. No ORM/database/consumer identity generation remains for governed entities.
5. JWT and REST tests reject bare UUIDs and wrong prefixes.
6. Migration integration tests prove conversion, constraints, invalid-data
   rejection, and auth-session invalidation.
7. Rust event and network-policy tests prove producer-owned IDs.
8. Frontend parsers, route parameters, stores, and response models use branded IDs.
9. Repository scans include Python, Rust, frontend, SQL, filenames, directories,
   and normative documentation with semantic allowlists for legitimate history
   and platform terminology.
10. Targeted tests pass before full backend, frontend, orchestrator, runner, and
    documentation checks are run.
