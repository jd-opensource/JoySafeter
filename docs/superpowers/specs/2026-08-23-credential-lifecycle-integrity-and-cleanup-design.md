# Credential Lifecycle Integrity and Cleanup Design

**Date:** 2026-08-23
**Status:** Approved; implementation evidence is tracked by phase below; Phase 2 retention and purge remain design-gated
**Evidence:** `docs/superpowers/evidence/2026-08-22-credential-lifecycle-deep-audit.md`

## 1. Goal

Make every persisted credential-bearing object self-consistent from creation through use, expiry, revocation, secret erasure, retention, and physical purge. Align backend, frontend, database constraints, audit, naming, and package ownership without silently breaking stored ciphertext, deployed environment variables, public API paths, or raw API keys held by users.

## 2. Scope

This design covers:

- project API keys;
- unified Credentials and Credential Groups;
- task identity credentials;
- session repository tokens;
- credential material-access audit rows;
- project and organization deletion interactions;
- frontend/API status and lifecycle contracts;
- encryption envelope and key rotation;
- compatibility names and internal package cleanup.

It does not redefine login/session-token federation, Kubernetes Secret resources, or unrelated business-resource retention.

## 3. Chosen Approach

Adopt **explicit state plus separate secret erasure and metadata purge**.

Rejected alternatives:

1. **Keep soft delete only.** Rejected because terminally deleted rows retain decryptable material indefinitely.
2. **Immediately hard-delete everything.** Rejected because relational and JSON history references are not yet purge-safe and audit/history requirements are unresolved.
3. **Add route-local checks and cleanup scripts.** Rejected because that preserves divergent authorization and creates non-resumable destructive behavior.

The selected model separates four concerns:

- **operational state:** may this object be used now;
- **material state:** does decryptable secret material still exist;
- **retention state:** how long metadata and audit must remain;
- **physical state:** may the database row be removed without violating references or history policy.

## 4. Global Invariants

1. Database constraints enforce assumptions used by authentication and lookup code.
2. Mutating project-scoped operations use one lifecycle-aware authorization policy, regardless of route shape.
3. A terminal delete erases secret material in the same transaction as the tombstone transition.
4. Management list/get paths never decrypt secret material.
5. Runtime material reveal remains purpose- and field-scoped and emits non-secret audit evidence.
6. Expiry, revoke, archive, delete, erasure, and purge are distinct transitions.
7. Retry or replay never moves a terminal timestamp forward or duplicates its transition audit.
8. Physical purge accounts for inactive relational references and persisted JSON history.
9. Cleanup is bounded, idempotent, resumable, observable, and dry-run capable.
10. Compatibility is retained only for a named external, deployment, or persisted contract with an exit condition.

## 5. Canonical State Models

### 5.1 API key

Persisted fields remain `created_at`, `expires_at`, and `revoked_at`; status is derived with this precedence:

1. `revoked` when `revoked_at IS NOT NULL`;
2. `expired` when `expires_at IS NOT NULL AND expires_at <= now()`;
3. `active` otherwise.

Transitions:

| Command | Allowed from | Result | Audit |
|---|---|---|---|
| Create | none | active or future-expiring | one `api_key.created` |
| Authenticate | active | success and throttled usage telemetry | optional sampled/use event |
| Authenticate | expired/revoked | denied | stable denial metric/audit policy |
| Revoke | active/expired | revoked with immutable first `revoked_at` | one `api_key.revoked` |
| Revoke again | revoked | no-op; same timestamp | no duplicate transition audit |
| Purge | revoked/expired past retention | row removed by cleanup coordinator | one purge summary, not raw key data |

Creation accepts optional `expires_at`. It must be timezone-aware and later than the transaction timestamp. Name must be trimmed and non-empty. Role is limited to the supported project-role vocabulary. Database constraints enforce these rules where PostgreSQL can do so safely.

`key_hash` becomes unique. Migration preflight must detect duplicates before adding the constraint; duplicates are revoked deterministically and reported for operator review rather than silently deleted. New IDs use the canonical UUIDv7 model default instead of service-generated UUIDv4.

Authentication guarantee: a revoke committed before authentication begins must be observed. A request that already authenticated may complete; the system does not claim retroactive cancellation of in-flight work. The final authentication query must include active-state predicates, and telemetry must not update a row that became revoked or expired.

### 5.2 Credential

Canonical lifecycle:

`active ↔ archived → deleted+material_erased → purged`

- `archived_at` is reversible and retains material.
- `deleted_at` is terminal.
- `material_erased_at` proves cryptographic material removal.
- Terminal delete replaces `data` with an empty object in the same transaction and records `material_erased_at` and `deleted_at` once.
- Metadata required for audit/history may remain until retention permits purge.
- Deleted credentials cannot be restored; archive remains the reversible operation.

Write-time display projection replaces read-time heuristic masking. Store non-secret display fields separately from encrypted material, with explicit field classification derived from the validated credential kind/schema. Arbitrary `service` fields default to secret. URLs are sanitized structurally: user-info and sensitive query values are never stored in display form.

### 5.3 Credential Group

Canonical lifecycle:

`active ↔ archived → deleted → purged`

Group terminal delete performs one transaction:

1. lock group;
2. lock non-deleted members in deterministic ID order;
3. validate blocking live session bindings;
4. erase every member’s material and tombstone every member;
5. tombstone the group;
6. write one group transition audit with member count plus per-member transition records or an explicitly approved aggregate format.

The implementation must choose one audit granularity before coding. Recommendation: per-member rows for forensic completeness plus a group summary row, all in the same transaction.

### 5.4 Task identity material

States are `available`, `consumed`, `expired`, `cancelled`, `terminal_failed`, then `purged` with respect to metadata. Any transition out of `available` clears `encrypted_credential` atomically. A sweeper claims expired or terminal rows in bounded batches and is safe to retry.

### 5.5 Repository token

Repository-token material has its own `expires_at`, `erased_at`, and rotation metadata instead of inheriting indefinite retention from Session metadata. Session archive does not imply immediate erasure unless product policy says archived sessions can never resume; session terminal deletion always erases before metadata purge.

### 5.6 Access audit

Access audit remains append-only to ordinary application roles, but not immortal. Recommended storage is monthly PostgreSQL range partitioning on `created_at`:

- current partitions retain existing INSERT-only triggers;
- retention drops whole expired partitions through a privileged maintenance role;
- purge emits an external/operator audit record with partition name, range, row count, and policy version;
- legal hold prevents eligible partition removal;
- user/org identifiers are pseudonymized or removed only under an approved privacy policy.

## 6. Authorization Convergence

Introduce one application-facing project gate with explicit capability and lifecycle intent:

```text
authorize_project(project_id, principal, required_capability, allow_archived)
```

- Reads that intentionally support archived projects pass `allow_archived=true`.
- Every mutation passes `allow_archived=false` unless the mutation itself is restore/delete/purge and its policy explicitly allows that state.
- Legacy active-context and explicit path-project routes call the same gate.
- API-key principals remain prohibited from API-key administration.
- Route path project, authenticated organization, persisted project organization, and write target must agree.

The immediate API-key fix is not a special-case `archived_at` check in one handler; it is migration of both route families onto this policy.

## 7. Database Integrity

### 7.1 API keys

Add or validate:

- unique constraint/index on `key_hash`;
- composite project/organization integrity, using a unique `(id, org_id)` target on projects and a composite FK from API keys;
- role CHECK for `admin`, `editor`, `viewer` unless the approved product contract removes ineffective `admin` keys;
- trimmed non-empty name CHECK;
- expiry CHECK `expires_at IS NULL OR expires_at > created_at`;
- partial composite list index on `(project_id, created_at DESC, id DESC) WHERE revoked_at IS NULL`.

Because expired rows are derived by time, a static partial index cannot safely use `now()`. Listing queries use the project/revocation index and apply expiry in the predicate or expose all non-revoked rows with derived status, depending on the endpoint contract.

### 7.2 Secret erasure

Add nullable `material_erased_at` to Credential and equivalent erasure timestamps to other sensitive stores. Backfill only after a preflight classifies deleted rows:

- deleted row with `{}` material: set `material_erased_at` to `deleted_at`;
- deleted row with ciphertext: erase in a bounded migration worker, then stamp;
- unreadable ciphertext: erase without decryption, record a non-secret failure classification, and continue;
- active/archived row: never mutate in this backfill.

### 7.3 Physical references

Do not change existing `RESTRICT`/`NO ACTION` constraints to broad CASCADE merely to make deletion pass. Cascades can erase history unexpectedly. The purge coordinator must explicitly handle:

- deleted Agent and Trigger foreign keys;
- Environment JSON references;
- Agent Version snapshots;
- Session snapshots;
- Session Credential Group association rows;
- Credential members before Credential Group;
- project-owned API keys and other sensitive records before Project.

Historical JSON policy recommendation: preserve immutable snapshots and replace purged IDs with a stable tombstone descriptor only through a versioned rewrite job; never leave an apparently live opaque ID that no longer resolves.

## 8. API and Frontend Contract

### 8.1 Canonical API-key DTO

List/create responses expose:

- `id`, `project_id`, `name`, `key_prefix`, `role`;
- `status`: `active | expired | revoked`;
- `created_at`, `expires_at`, `revoked_at`, `last_used_at`;
- raw key only in the create response.

Create accepts optional `expires_at` and later may support a bounded duration preset. Revoke is represented as a revoke action in UI copy and API documentation even while the compatibility endpoint keeps HTTP `DELETE`.

### 8.2 Route migration

Canonical management routes are explicit-project routes. `/api/v1/auth/api-keys` remains temporarily as a compatibility route because public documentation and clients use it. Both delegate to the same application command/query service.

Removal gate for the old route:

1. mark deprecated in OpenAPI and documentation;
2. emit route-family metrics without recording keys;
3. observe a defined zero/acceptable usage window;
4. publish removal date;
5. remove route and its frontend fallback together.

The redirect-only `/managed/api-keys` page and no-`projectId` component branch can be removed once all internal links and tests prove the canonical project-token page is the only entry. No compatibility shim is needed for unreachable internal code.

### 8.3 Management projection

List/get endpoints read only metadata plus stored display projection. They do not instantiate a decryptor. Corrupt ciphertext is surfaced only when an authorized runtime access actually requests that credential, and it cannot abort unrelated management rows.

## 9. Encryption-Key Rotation

Introduce a versioned envelope:

```text
enc:v2:<key_id>:<base64(nonce+ciphertext)>
```

For v2, the exact ASCII prefix `enc:v2:<key_id>:` is AES-GCM associated data. This binds the
version and key identity to the authentication tag, so relabeling an envelope to another configured
key ID fails even when two IDs accidentally reference identical key bytes. The pre-release,
unauthenticated v2 draft is intentionally not accepted as a compatibility format.

Configuration becomes a keyring with one write key and one or more read keys. During migration:

- readers continue accepting legacy `enc:` and `enc:v1` through the existing deployment variable;
- new writes switch to v2 only after every deployed reader supports it;
- a resumable rewrap worker locks bounded rows, decrypts with the source key, encrypts with the active key, and records progress without plaintext;
- online rewrap rejects plaintext and malformed stored material with a location-only error instead of silently normalizing a storage-boundary violation;
- one rewrap call uses a database savepoint across all material stores, so a later-store failure cannot leave earlier-store mutations available for accidental commit;
- startup validates key syntax and decrypts a database canary for every required key ID;
- concurrent canary initialization uses insert-if-absent semantics: the first committed row wins, every loser validates that persisted ciphertext, and a savepoint removes the caller's partial canary set when validation fails;
- the canary table enforces the runtime key-ID grammar and an exact, non-empty envelope prefix at the database boundary;
- startup inventories persisted envelope generations, classifies non-object credential JSON and null/non-string material as invalid, and rejects removal of a legacy or v2 read key while any stored material still references it;
- rollback retains the previous read key until no ciphertext references it and the rollback window closes.

`LegacyV1MaterialProtector` should be internally renamed only when callers migrate atomically. The persisted `enc:v1` label is not renamed. `JOYSAFETER_VAULT_ENCRYPTION_KEY` remains a deprecated read alias during a measured deployment window; it is removed only after deployment inventory proves the new keyring variables are universal.

Implemented end state: the neutral internal boundary is `VersionedMaterialProtector`; canaries are explicitly initialized before rollout, all services fail closed on configured-key mismatch, and the rotation inventory reports only surface/envelope/count tuples. Old read keys remain required while any inventory row names their envelope or during the declared rollback window.

## 10. Package and Naming End State

### Backend

- `joysafeter_application/api_keys/`: command/query service, state derivation, DTO-neutral results.
- `joysafeter_api/api/v1/api_keys.py`: request/response schemas and both canonical/compatibility routes.
- `joysafeter_domain/credentials/`: pure policies, value objects, lifecycle transitions, no SQLAlchemy or `AppError`.
- `joysafeter_application/credentials/`: use cases and domain-to-application error mapping.
- `joysafeter_infrastructure/credentials/resource_repository.py`: Credential persistence.
- `joysafeter_infrastructure/credentials/group_repository.py`: Group persistence.
- `joysafeter_infrastructure/credentials/material_projection.py`: encryption and display projection persistence.
- `joysafeter_infrastructure/credentials/reference_repository.py`: physical and runtime dependency queries.
- `joysafeter_application/sensitive_material_cleanup/`: cross-store erasure/purge orchestration.

Rename the DB-backed `CredentialGroupService` to a repository/facade name before or during extraction; keep the UoW application service as the sole `CredentialGroupService`. Move SQLAlchemy group invariants out of Domain. Move `credential_binding_errors.py` translation out of Domain. Remove `CredentialService.get_credential_data()` after the zero-production-caller architecture test is in place.

### Frontend

- keep page routing thin;
- move API-key query/mutation hooks and DTOs into one feature module;
- split list, create dialog, revoke dialog, and status presentation;
- delete unused `frontend/types/managed.ts::ApiKeyInfo`;
- remove the no-`projectId` API branch after canonical-route tests pass.

### Documentation

`docs/api/openapi.md` must stop presenting removed `/secrets`, `/vaults`, `vault_ids`, or delete semantics as current. Historical migration documents remain historical and are not rewritten to pretend old names never existed.

## 11. Delivery Phases

### Phase 0 — safety stopgaps

1. Converge API-key mutation authorization and block archived projects.
2. Add duplicate-hash preflight, deterministic remediation, and uniqueness.
3. Make revoke atomic/idempotent with one audit transition.
4. Treat Credential/Group tombstones as organization-deletion blockers so deletion fails explicitly instead of at a late FK.
5. Stop management reads from revealing URL/user-info/query secrets; until write-time projection lands, return conservative redacted placeholders without decrypting arbitrary fields.

### Phase 1 — complete vertical lifecycles

1. Deliver API-key expiry/status across schema, service, routes, docs, and UI.
2. Add same-transaction Credential/Group material erasure and backfill existing tombstones.
3. Add task-identity terminal erasure and repository-token retention.
4. Add throttled/state-aware API-key usage telemetry and denial observability.
5. Introduce v2 keyring readers, canary validation, then switch writers and rewrap.
6. Persist non-secret management display projections.
7. Add an offline, cursor-paged, read-only decrypt-verification pass across every persisted sensitive-material store; keep it outside API, worker, and orchestrator startup paths.

### Phase 2 — retention, purge, and structure

1. Approve retention durations and legal-hold behavior.
2. Partition access audit and add privileged retention execution.
3. Implement the checkpointed purge coordinator and JSON tombstone rewrite.
4. Replace organization delete with preflight plus asynchronous purge orchestration when required.
5. Split oversized backend/frontend modules and remove proven-dead facades/types/branches.
6. Deprecate and later remove old routes and deployment names using telemetry gates.
7. Correct current API documentation and preserve historical records separately.

Each phase has its own migration, rollout, rollback, and real PostgreSQL test gate. Phase 2 destructive cleanup cannot be bundled into Phase 0.

## 12. Concurrency and Transaction Rules

- Lock order: Project → Group → Credential → referencing mutable rows → cleanup job row.
- Revoke uses one conditional UPDATE and distinguishes transitioned, already revoked, and not found.
- Secret erasure and tombstone audit commit together.
- Cleanup claims independent work with `FOR UPDATE SKIP LOCKED`; it never holds locks while calling external systems.
- Every batch stores a high-water mark/checkpoint and can be replayed.
- Dry-run executes the same discovery queries but performs no mutation.
- Failure records contain IDs, phase, stable code, and retry metadata, never ciphertext or decrypted values.
- Metrics expose eligible, claimed, erased, purged, blocked, failed, retried, and oldest-pending age.

## 13. Verification Gates

Every phase requires:

- migration upgrade/downgrade or documented irreversible boundary on disposable PostgreSQL 15;
- duplicate, cross-org, archived-project, expiry-boundary, repeated-revoke, and concurrent revoke/auth tests;
- ciphertext erasure assertions using direct SQL, not only API projections;
- corrupt-ciphertext isolation tests;
- terminated/deleted reference and JSON-history purge tests;
- organization deletion dry-run and failure-resume tests;
- keyring mixed-reader/writer and rollback-floor tests in Python and Rust;
- frontend contract tests for status, expiry, revoke wording, and canonical route use;
- architecture tests preventing SQLAlchemy in Domain, duplicate service names, and reintroduction of plaintext facades;
- residual scans for obsolete routes, names, compatibility branches, and unowned sensitive fields.

## 14. Cleanup Exit Criteria

Cleanup is complete only when:

1. every sensitive persisted field has an owner, lifecycle, erasure trigger, retention rule, and audit policy;
2. no terminally deleted object retains decryptable material;
3. organization/project deletion either lists blockers or completes a checkpointed purge without FK errors;
4. no management read decrypts material;
5. no active reader depends solely on the retired encryption key or envelope;
6. compatibility surfaces have evidence-backed retention or a dated removal gate;
7. obsolete internal facades, duplicate names, dead branches, stale current docs, temporary databases, and probe scripts are removed.
