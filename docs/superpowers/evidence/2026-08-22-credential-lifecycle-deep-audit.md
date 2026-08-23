# Credential Lifecycle Deep Audit Evidence

**Audit date:** 2026-08-22
**Scope:** API keys, unified Credentials, Credential Groups, runtime material consumption, audit attribution, reference compatibility, deletion/retention, naming, and package ownership
**Status:** Re-opened on 2026-08-23 and actively implemented. Phase-specific evidence below supersedes the original pre-implementation findings; retention, physical purge, and final structural cleanup remain open.

## 1. Required Invariants

1. A credential mutation and its required audit record commit or roll back together.
2. Authentication identifies the actual principal, not only the human account that created it.
3. Runtime consumers may reveal only fields authorized for their declared purpose.
4. Reference validation must not reveal credential material.
5. Every material reveal must be attributable to project, credential, purpose, consumer, and runtime scope without recording secret values.
6. Archive, delete, revoke, expiration, and purge must have distinct state transitions and explicit retention rules.
7. Compatibility names and formats remain only when an active persisted, deployed, or external contract requires them.
8. Domain code must not depend on Application composition or Infrastructure implementations.

## 2. Lifecycle Inventory

### 2.1 Project API Keys

| Stage | Current owner | Current behavior | Audit result |
|---|---|---|---|
| Create | `joysafeter_application/api_keys/service.py` + auth route | Generates a one-time raw key, stores SHA-256 hash and display prefix, flushes inside the caller transaction | `api_key.created` is now written before the shared commit |
| Authenticate | `joysafeter_shared/common/joysafeter_auth/dependencies.py::_auth_via_api_key` | Validates key, creator access, project scope, role cap, revoke time, and expiry | Context now carries `principal_type="api_key"` and the exact key ID as `principal_id` |
| Use telemetry | `_auth_via_api_key` | Conditionally updates `last_used_at` only when the stored value is null or older | Best effort; authentication remains available if telemetry commit fails |
| List | `ApiKeyService.list_project_keys_page` | Returns non-revoked keys only | Read is not separately audited |
| Revoke | `ApiKeyService.revoke_key` + auth route | Sets `revoked_at`; route writes audit and commits once | `api_key.revoked` is atomic with revocation |
| Expire | Model/auth dependency only | `expires_at` is enforced during authentication | Create request, response DTO, and management UI do not expose expiry configuration/status |
| Purge | None | Revoked/expired rows remain indefinitely | No retention or purge contract exists |

Implemented during this audit:

- Moved the SQLAlchemy API-key service out of Domain into `joysafeter_application/api_keys/`.
- Removed unused `get_by_hash`, `touch_last_used`, and non-paginated `list_project_keys` methods.
- Changed create/revoke from service-level commit plus best-effort audit to one route-owned transaction.
- Added exact API-key principal attribution to the shared auth context and generic audit details.
- Replaced ORM mutation of `last_used_at` with a monotonic conditional SQL update and copied primitive context fields before the best-effort commit.

### 2.2 Unified Credentials and Groups

| Transition | State effect | Dependency behavior | Restore behavior |
|---|---|---|---|
| Create/update | Active row with encrypted `data` | Binding policy validates kind, project, identity, and authorized fields | Not applicable |
| Archive | Sets `archived_at` | Active references block or produce lifecycle impacts according to the registry policy | Supported where the resource lifecycle exposes restore |
| Delete credential | Sets `deleted_at` | Live references are rejected before mutation | Terminal; no deleted-resource restore path |
| Delete group | Sets group `deleted_at` and soft-deletes members in the same operation | Active session bindings block deletion | Terminal; no deleted-group restore path |
| Material load | Requires a validated usage binding | Python selects authorized encrypted fields before decryption | Not applicable |
| Purge | None | Physical foreign keys and JSON snapshot references are not reconciled | No purge job or tombstone policy |

Mutation audit is transactionally coupled through `CredentialUnitOfWork` and receives one explicit immutable `CredentialAuditActor` from every composition root. HTTP writes preserve the authenticated user or API-key principal plus request origin; scheduler and internal-only callers must supply a named system principal. No credential-capable Application service retains an omitted-actor fallback.

## 3. Material Consumption Matrix

### 3.1 Python consumers

| Consumer | Usage | Validation boundary | Reveal behavior | Runtime attribution available at call site |
|---|---|---|---|---|
| Quickstart | Model inference | `validate_model_inference` | Authorized fields selected before decrypt | User/project and request are available in API route |
| Skill authoring | Model inference | `validate_model_inference` | Authorized fields selected before decrypt | User/project and request are available in API route |
| Trigger webhook auth | Webhook authentication | `WebhookAuthService` → `binding_service.validate` | One authorized field read after decrypt | Application service receives either the authenticated request actor or explicit `webhook_request` actor |
| Credential management list/get | Masked management view | Repository/application projection | No plaintext response | Query-only compositions use explicit named system actors; mutation routes preserve the request actor |
| Repository access | Repository token | Purpose-specific adapter | Uses the shared legacy-v1 protector | Constructed inside a Domain service through an Application composition helper |
| Task identity | Agent identity material | Purpose-specific adapter | Uses the shared legacy-v1 protector | API capture boundary has request context |

`ManagedCredentialMaterialAdapter.load()` is the strongest current reveal boundary in Python: it validates a capability-bearing binding, loads encrypted data, selects requested/authorized fields, and decrypts only those selected fields.

### 3.2 Rust consumers

| Consumer | Usage | Current path | Current reveal behavior |
|---|---|---|---|
| Model runtime | Model inference | catalog metadata → `CredentialMaterialAccessService` → field-scoped store load | Sandbox resolution decrypts the authorized model profile fields; Harness decrypts only the optional model-name field when no explicit model is configured |
| Environment variables | Environment injection | Store → environment resolver | Intentionally decrypts all fields because this usage explicitly injects the complete credential map |
| HTTP egress | Header/cookie/bearer injection | `CredentialStore.get_active_with_field_selector` → egress resolver | Fixed in this audit: validates metadata first, then decrypts only the configured injection field |
| MCP | Session group membership | Harness metadata lookup; Sandbox `CredentialMaterialAccessService` → MCP resolver | Harness reads URL metadata only; Sandbox egress decrypts only `token_value` for the supported `static_bearer` scheme |
| Session snapshot validation | Reference validation | snapshot builder → `CredentialStore.lock_active_metadata` | Fixed in this audit: validates state, identity, and required field names without decrypting values |

The remaining whole-object reveal is limited to explicit Environment Injection, whose contract authorizes exporting the complete credential map. Harness no longer owns an internal secret map: environment material is injected by `SandboxResolver`, and model material is not reloaded except for an optional model-name fallback.

## 4. Audit Coverage Matrix

| Event class | Current coverage | Gap |
|---|---|---|
| Credential mutation | Same-transaction `CredentialAuditEntry`; request actor, exact API-key principal, IP, and user agent are retained | Material-access audit remains separate from mutation audit |
| Credential group mutation | Same transaction and actor contract as Credential mutation | Material-access audit remains separate from mutation audit |
| Environment credential binding | Initial binding and later binding changes emit same-transaction `environment.credentials.updated`; existing-runtime impact remains update-only | Does not yet emit per-material-reveal events |
| Session snapshot creation | `session.snapshot.created` retains request actor for API/session/task callers and explicit system actor for background callers | Does not include referenced credential IDs, groups, or usage purposes |
| Python material reveal | `CredentialMaterialAccessService` owns validation → scoped reveal → append-only audit; Quickstart, Skill AI Authoring, and Webhook auth use it | Runtime Rust emitters remain separate |
| Rust material reveal | `CredentialMaterialAccessService` writes append-only success/denied/failed rows for model, environment, HTTP egress, and MCP egress | Success is deduplicated per generation; failures remain append-only |
| API-key create/revoke | Generic security audit | Fixed: atomic and principal-aware |
| API-key authentication use | `last_used_at` only | No per-use audit event; timestamp is intentionally best effort |

Writing audit inside the Python material adapter is not sufficient: the adapter has the credential binding but not a complete actor/consumer/runtime context. Python now keeps that orchestration in `CredentialMaterialAccessService`, while `ManagedCredentialMaterialAdapter` remains limited to capability validation, field selection, and decryption. Rust has the same context problem and additionally needs a durable write strategy that does not make every hot-path reveal contend on the task transaction.

The implemented access-audit contract stores these non-secret fields:

- `event_type`: `credential.material.accessed`
- `project_id`
- `credential_id`
- `credential_kind`
- `usage`
- `consumer_type` and `consumer_id`
- `principal_type`, `principal_id`, `user_id`, `org_id`, `role`, `ip_address`, and `user_agent`
- `session_id`, `task_id`, and `generation` when runtime-scoped
- `field_names`, never values
- `result` and a stable error code for denied/failed access

Runtime success events should be idempotent on `(session_id, generation, credential_id, usage, consumer_type, consumer_id)`. Denials and failures should remain individually observable. The exact persistence transport must be chosen before implementation so auditing cannot silently downgrade credential availability or create an unbounded synchronous hot path.

Python access auditing now fails closed: a successful reveal is not returned when its audit record cannot be persisted. Validation failures are recorded as `denied`; storage, field-selection, key-configuration, and ciphertext failures are recorded as `failed` with stable non-secret codes. The audit writer uses an independent SQLAlchemy session and the audit table deliberately has no live credential foreign key, preventing lock coupling with trigger create/update transactions.

The former Domain-layer `joysafeter_trigger_webhook_auth_service.py` has been removed. Webhook credential orchestration now lives at `app/joysafeter_application/credentials/webhook_auth_service.py`; pure trigger configuration normalization remains in the Domain policy. Authenticated trigger management preserves the exact request principal, while public webhook ingress is explicitly attributed as `principal_type=webhook_request`, `principal_id=anonymous`, with the trigger retained as the consumer identity.

## 5. Reference Compatibility

The reference contract at the audit baseline was intentionally asymmetric:

- Read: `legacy-v0`, `v1`, and `v2`.
- Production write: `v1` only.
- `v2`: codec grammar and test contract only; no production writer switch exists.
- Historical Agent Version and Session Snapshot documents are not rewritten.

This is a real rollout boundary, not dead compatibility code. The frozen decision and database preflight are recorded in `docs/superpowers/evidence/2026-08-19-credential-domain-closure-v1-freeze.md`. Changing new writes to `v2` requires a separate rolling-deployment plan, reader-floor proof, rollback-floor proof, and mixed-version runtime validation.

At that baseline, the `LegacyV1MaterialProtector` name could not be removed without preserving persisted ciphertext compatibility and environment configuration. Phase 1 later replaced the internal name atomically while retaining explicit `enc:`/`enc:v1:` readers.

## 6. Retention and Physical Deletion

No production retention policy, purge API, or purge worker exists for Credentials, Credential Groups, or API Keys. Consequently, ciphertext in soft-deleted Credential rows and hashes in revoked API-key rows are retained indefinitely.

A safe purge cannot be implemented as a generic age-based `DELETE` because:

- Credential-to-group membership uses restrictive project-scoped foreign keys.
- Agent, Trigger, Environment, and other live reference surfaces may still point at a credential.
- Session-to-group associations constrain group deletion.
- Historical Agent/Session snapshot JSON contains credential references without relational foreign keys.
- Audit evidence must survive resource deletion, requiring tombstone semantics rather than dangling live-object assumptions.

Any purge design must define grace periods, legal/audit retention, historical-session behavior, relation cleanup order, dry-run reporting, idempotency, and a fail-closed dependency scan.

## 7. Naming and Package Ownership

### Confirmed canonical names

- Public management routes: `/credentials` and `/credential-groups`.
- Active domain concepts: Credential and Credential Group.
- Legacy `/managed/secrets` and `/managed/vaults` frontend routes remain redirect-only compatibility edges.
- Historical documents may retain historical terminology when describing migrations.

### Confirmed compatibility names

- `JOYSAFETER_VAULT_ENCRYPTION_KEY`: retained only as the legacy-envelope read key during the measured v2 migration window.
- `enc:` / `enc:v1:`: persisted compatibility formats; the internal `LegacyV1MaterialProtector` name and files have been removed.
- v1 credential references: frozen production write format for rollback safety.
- `cnkey_`: the only API-key generator prefix, introduced with the original API-key implementation. Verification treats the raw key as opaque, but no replacement prefix has been selected or documented, so writer churn is deferred.

### Structural result

The Domain → Application reverse-import inventory is empty and enforced by an architecture test. Credential composition, mutation coordination, Session creation, Environment binding coordination, Trigger firing, and Agent persistence orchestration now live in Application; Domain retains policies, schemas, state rules, and pure validation. Removed service modules and `management_service.py` have no compatibility shims.

The six-file inventory was audited before the first ownership move:

| Previous Domain module | Application dependency and transaction boundary | Production callers | Disposition |
|---|---|---|---|
| `agent_trigger_execution.py` | Builds `CreateCredentialAwareSession`, then coordinates committed snapshot creation, task submission, enqueue, and compensating cleanup | Trigger fire orchestration and scheduler | Moved together with `joysafeter_trigger_fire_service.py` to `joysafeter_application/triggers/`; old modules removed without compatibility shims |
| `joysafeter_agent_service.py` | Locks and validates model credential bindings inside Agent create/update transactions | Agent API plus read consumers in Session, Task, and scheduler paths | Split Application-owned create/update coordination from stable query and lifecycle behavior before moving |
| `joysafeter_environment_service.py` | `commit_update` writes binding audit, records runtime impacts, commits, and nudges after commit | Environment API; read methods are also used by trigger/runtime code | Move the credential-aware command coordinator, not the read/reference-check surface |
| `joysafeter_session_resource_service.py` | Composes repository-token protection and owns resource mutation commits | Session API only; no Domain production caller or package re-export | Moved intact to `joysafeter_application/sessions/resource_service.py`; old module removed with no compatibility shim |
| `joysafeter_session_service.py` | Wrapped credential-aware snapshot creation and retained a legacy direct create path with credential-group validation | Snapshot creation is called by Session API, Task API, and trigger execution; direct low-level create had no production caller | Creation now enters through `joysafeter_application/sessions/creation_service.py`; the bridge and test-only direct writer were removed, while query/event/lifecycle behavior remains in Domain |
| `joysafeter_trigger_service.py` | Validated webhook credential bindings during create/update and resolved material for request verification/sample generation | Trigger API; non-credential lifecycle methods are used by Agent, Project, and scheduler code | Completed: `TriggerApplicationService` now owns create/update, webhook authentication, manual/webhook fire orchestration, sample generation, scheduler notification, and commit error translation. Domain retains query, delete, scheduling state, and project/agent lifecycle behavior |

The first migration selected `SessionResourceService` because its whole responsibility is application orchestration, it has one production import site, and its old Python module path is not an exported or persisted compatibility contract. Public HTTP routes, request/response shapes, database columns, `enc:v1` ciphertext, and `JOYSAFETER_VAULT_ENCRYPTION_KEY` remain unchanged.

## 8. Actions Completed in This Audit

1. API-key create/revoke and audit now share one transaction.
2. API-key auth contexts and generic audit details identify the exact key principal.
3. `last_used_at` is monotonic and rollback-safe for auth-context construction.
4. API-key persistence orchestration moved from Domain to Application.
5. Dead API-key service methods were removed.
6. `docs/ARCHITECTURE.md` now shows current Credential routes and the Application/Infrastructure ownership split instead of `secret/vault` services.
7. A no-database documentation contract prevents the old source-layout names from returning.
8. Rust snapshot validation now uses a material-free `CredentialMetadataRecord` and `lock_active_metadata`; encrypted field names are checked without revealing values.
9. Rust material handling now has a field-selective `reveal_fields` primitive with tests proving an invalid unrequested field is not decrypted.
10. Rust HTTP egress now loads only its configured injection field, and MCP loading reveals only `token_value`.
11. Rust model loading now intersects stored field names with the selected catalog profile before decrypting, preserving optional profile fields while excluding unknown data.
12. Credential, Credential Group, Environment binding, and Session snapshot audit writes now use one immutable `CredentialAuditActor` contract; request paths retain human/API-key identity plus request origin, while non-request paths persist an explicit system principal.
13. Environment creation now audits initial credential bindings. Audit-change detection is separated from runtime-impact detection, so a new environment records the binding without scheduling a meaningless restart for a runtime that does not yet exist.
14. Added `joysafeter_credential_access_audits` as a database-enforced append-only event table. It stores identifiers, usage, field names, result, and error code only; no plaintext material or generic payload column exists.
15. Runtime success deduplication uses PostgreSQL 15 `NULLS NOT DISTINCT`, so a nullable `consumer_id` cannot bypass idempotency. The audit keeps an immutable typed credential ID without a foreign key, avoiding lock coupling with credential mutations and preserving evidence after purge.
16. Removed the dead `HarnessInput.secrets` material cache. It was populated but deliberately discarded by both `build_setup_sandbox` and `build_start_task`, so environment and API-key decryption there had no runtime consumer.
17. Preserved `SetupSandbox.secrets` and `StartTask.secrets` as wire-compatibility fields for rolling runner deployments, while documenting and testing that the current orchestrator always sends them empty.
18. Added a model-runtime configuration path that validates credential metadata without decryption when an explicit model exists, and decrypts only the catalog `model_key` when fallback is required.
19. Moved `SessionResourceService` from Domain to `joysafeter_application/sessions/`, updated its only production import and test imports, and removed the old module without a compatibility shim. Repository-token encryption and all HTTP/database contracts remain unchanged.
20. Added `SessionCreationService` as the sole composed entry point for credential-aware Agent Session creation. Session API, Task API, and trigger execution now call it directly; the Domain bridge and unused low-level session writer were removed. Its actor is mandatory and is supplied by the initiating request or the explicit upstream system caller.
21. Added `EnvironmentCredentialService` under `joysafeter_application/environments/` as the sole owner of Environment credential-reference validation and credential-aware commit coordination. The API-private validator, Domain `commit_update`, Domain audit actor state, and Domain → Application imports were removed without compatibility shims. Audit action, error codes, impact ordering, and commit/nudge sequencing remain unchanged; the actor is mandatory.
22. Moved `AgentTriggerExecutor` and `TriggerFireService` together from Domain to `joysafeter_application/triggers/`. Scheduler, Trigger service, tests, snapshot architecture checks, and typed-ID inventories now use the Application paths; both old modules were removed without shims. Trigger/session/task idempotency, lock ordering, compensating cleanup, and API response contracts remain unchanged.
23. Added `TriggerApplicationService` as the complete Trigger command surface. Create/update now keep target validation, deterministic Trigger/credential locking, webhook field-scoped validation, name-conflict translation, commit/refresh, and post-commit scheduler notification in Application; webhook authentication, manual/webhook firing, and signed sample generation use the same Application entry point. `JoySafeterTriggerService` retains only query, delete, scheduler-state, and project/agent lifecycle responsibilities. No old command-method shims or fallback audit principals remain.
24. Replaced the mixed-layer `JoySafeterAgentService` with explicit Agent packages: pure configuration/assets/snapshot rules in `joysafeter_domain/agents`, command/query/lifecycle orchestration plus ports in `joysafeter_application/agents`, and SQLAlchemy, credential-binding, runtime, trigger-lifecycle, and unit-of-work adapters in `joysafeter_infrastructure/agents`. API, Session, Task, and scheduler callers now enter through the Application composition root; the old service file, class, imports, API-private business helpers, and test references were removed rather than retained as compatibility shims.
25. Standardized Agent command failure handling on unit-of-work rollback so validation and conflict exits release Agent, Environment, and Credential row locks. Real PostgreSQL regression exposed two tests that read expired ORM attributes after rollback; those tests now capture scalar identifiers before the operation, preserving the rollback contract instead of weakening transaction cleanup.
26. Propagated one actor unchanged through Trigger API or scheduler → `TriggerApplicationService` → `TriggerFireService` → `AgentTriggerExecutor` → `SessionCreationService`. Manual and test-fire requests retain the authenticated principal, public webhooks use `webhook_request/anonymous`, and scheduled execution uses `system/trigger_scheduler`.
27. Made `audit_actor` mandatory on Credential, Credential Group, Environment, Session, webhook-auth, Trigger fire, and Trigger execution Application entry points. All production and test composition roots now supply an explicit request or named system actor; architecture tests reject optional defaults.
28. Deleted `credentials/management_service.py`, removed dynamic `__getattr__` forwarding and compatibility-only nudge delegation, and retained only explicit Application methods. The old module name remains solely in negative architecture assertions and historical design records.
29. Completed Credential Group membership audit details with both `target_id=<credential_id>` and `credential_group_id=<group_id>`, and persisted the full access actor context (`user_id`, `org_id`, `role`, `ip_address`, `user_agent`) plus the principal/time index in the unbaselined `20260822_000001` migration.
30. Removed the unused Rust `CredentialStore.get_active_fields` entry point instead of registering dead SQL as an exception. The remaining field-selective path validates metadata before choosing fields, and the reverse-census exception registry was refreshed by exact callsite and ownership.

## 9. Ordered Remediation Gates

1. **Usage audit contract:** implemented for current Python and Rust material consumers; future consumers must use the same stable fields and no-plaintext rule.
2. **Rust selective reveal:** complete; retain whole-field reveal only for the explicitly all-fields Environment Injection usage.
3. **Application ownership:** complete for Agent and the other credential-aware flows audited here; the Domain → Application reverse-import inventory is empty and guarded by architecture tests.
4. **Mutation actor propagation:** complete; all Credential-capable Application roots require an explicit actor, and Trigger-originated Session snapshot events preserve the initiating actor end to end.
5. **API-key expiry:** expose creation policy, response status, UI controls, and tests as one vertical slice.
6. **Retention/purge:** implement only after a written retention policy and reference/tombstone model are approved.
7. **Naming migrations:** change `cnkey_`, the encryption-key environment variable, or v1 formats only through explicit compatibility migrations.

## 10. Verification Evidence

- Targeted Ruff check for API-key/auth files: passed.
- Targeted Python compile check for API-key/auth files: passed.
- API-key/auth regression suite: `41 passed, 22 warnings`.
- Credential mutation/actor cross-module regression suite: `296 passed, 291 warnings`.
- Credential access-audit model tests: `3 passed`.
- Full credential migration suite with the new head: `35 passed`.
- New architecture source-layout contract: passed.
- Rust credential unit suite and `cargo check`: passed; existing unrelated compiler warnings remain.
- Rust PostgreSQL `credential_store_integration`: `18 passed`.
- Rust Harness-focused suite: `24 passed`; this includes snapshot generation fences, MCP metadata-only resolution, and model-name-only material access.
- Rust recovery failure propagation: `1 passed`.
- Python credential architecture boundary suite: `63 passed, 60 warnings`.
- Session-resource plus credential-boundary regression after ownership migration: `90 passed, 86 warnings`.
- Moved session-resource typed-ID architecture parameter: `1 passed`.
- Credential-aware session creation, group lifecycle, resource lifecycle, and trigger replay regression after removing the Domain creation bridge: `104 passed, 104 warnings`.
- Environment credential ownership migration against an isolated PostgreSQL database: `160 passed, 138 warnings`; this covers reference validation, audit/impact transaction ordering, lifecycle behavior, atomic refresh, and reference boundaries. A first run against the live application database exposed expected external lock contention from running API/worker/orchestrator containers, so the authoritative run used `joysafeter_test_credentials`.
- Trigger execution/fire ownership migration against the isolated PostgreSQL database: `210 passed, 174 warnings`; the moved typed-ID execution graph parameter set passed `24 passed`, and the snapshot caller architecture check passed `1 passed`. A broader typed-ID file run also surfaced four pre-existing failures in unrelated runtime-status, Rust sandbox-resolver, Session credential-group, and Rust Harness assertions; none referenced the moved trigger files.
- Trigger command-surface ownership migration against the isolated PostgreSQL database: final clean-tree run `227 passed, 174 warnings` in `58.64s`. The targeted architecture boundary checks passed `2 passed, 65 deselected`; collection found all `227` selected tests; targeted Ruff and format checks passed. Domain → Application reverse imports decreased from two files to the single documented Agent service.
- Agent layering final PostgreSQL regression: the credential/Agent/Trigger lifecycle suite passed `332 passed, 279 warnings` in `84.25s`; the disjoint remaining Agent, skill-reference, and sandbox-state suite passed `81 passed, 20 warnings` in `9.53s`. The two original failures were reproduced independently and then passed `2 passed, 2 warnings` after correcting post-rollback ORM test access.
- Agent architecture and cleanup verification: targeted Ruff passed, all `27` affected files were already formatted, targeted Python compilation passed, the two Agent dependency-boundary tests passed, `git diff --check` passed, Domain → Application imports are zero, and the only remaining old Agent-service/path/helper strings are negative architecture assertions.
- Credential actor/facade completion regression against ephemeral PostgreSQL: `649 passed, 468 warnings` across all 27 direct callers changed by the explicit-actor contract.
- Final Credential/Trigger lifecycle regression against ephemeral PostgreSQL: `935 passed, 517 warnings` across 49 Credential, Trigger, Session, Environment, Agent, migration, API, and architecture files. The warnings are the existing SQLAlchemy table-cycle warning emitted during database cleanup.
- Rust Credential verification after removing the unused `get_active_fields` entry point: `cargo fmt --check` passed; Credential Store `18 tests`, snapshot linearization `11 tests`, SQL architecture `28 tests`, and all `7` top-level runtime-contract cases passed against a freshly migrated disposable PostgreSQL 15 container.
- Final Python quality gates: Ruff check passed, Ruff format check reported `90 files already formatted`, Python `compileall` passed, Alembic reports the single head `20260822_000001`, and `git diff --check` passed.
- Final residual scans found no optional Credential audit actor, no `management_service` production/test import, no Credential Application `__getattr__`, no `compatibility_after_commit`, and no Rust `get_active_fields`; the sole `management_service.py` occurrence is the negative architecture assertion that enforces deletion.
- Full Python test collection after actor/facade completion found `2354 tests`.
- Full `test_documentation_contracts.py`: two pre-existing fenced-code parsing failures remain outside this audit change.
- Repository documentation checker: one pre-existing broken anchor remains at `CONTRIBUTING.md:114` targeting `DEVELOPMENT.md#using-pre-commit-hooks`.

## 11. 2026-08-23 Re-opened Lifecycle Audit

The earlier “inventory complete” statement covered the then-inspected runtime reveal and layering paths, not the full creation-to-erasure lifecycle. The audit was therefore re-opened and extended through API/UI contracts, database constraints, archived-project authorization, terminal deletion, organization deletion, historical references, encryption-key rotation, and all other persisted sensitive-material stores.

### 11.1 Root-cause matrix

| Severity | Surface | Verified failure or gap | Root cause | Required invariant |
|---|---|---|---|---|
| P0 | API-key identity | `key_hash` is indexed but not unique; duplicate rows make authentication raise `MultipleResultsFound` | Authentication assumes uniqueness that the database does not enforce | One raw key hash identifies at most one row |
| P0 | API-key authorization | The legacy write route rejects an archived active project with `PROJECT_ARCHIVED`, while the explicit `/projects/{project_id}/api-keys` admin dependency allows the same archived project and the create route persists a key | `require_joysafeter_project_admin` validates project existence and role but not lifecycle state; route families use different write gates | Every mutating route rejects archived projects through one lifecycle-aware authorization policy |
| P0 | Organization deletion | Deleted Credential/Group tombstones are omitted from `_project_resource_blockers`; project deletion then fails on `NO ACTION` foreign keys and rolls back | Logical visibility rules were reused as physical-deletion dependency rules | A delete preflight reports every physical blocker or executes a complete ordered purge; it must never discover blockers as a late FK 500 |
| P0 | Credential deletion | Terminal soft delete sets `deleted_at` but retains encrypted `data`; group deletion does the same for every member | Logical lifecycle and secret-erasure lifecycle are conflated | Terminal deletion makes secret material unrecoverable in the same transaction while retaining only an explicit metadata tombstone |
| P0 | Management reads | List/get decrypt every field before masking by field name; arbitrary service fields and URL query/user-info secrets can be returned in plaintext, and one corrupt field aborts the entire list | No write-time display projection or sensitivity metadata exists; presentation is inferred after full decryption | Management reads never decrypt secret material and one corrupt historical ciphertext cannot take down unrelated rows |
| P1 | API-key lifecycle | Create cannot set expiry; DTO/UI do not expose expiry or derived status; list treats expired rows as active | Expiry exists only as an authentication-time predicate, not a vertical lifecycle contract | Create, list, status, authentication, revoke, and purge share one explicit state model |
| P1 | API-key revoke | Repeated revoke returns success, advances `revoked_at`, and emits another audit row | Mutation loads any row and overwrites state without an active-state predicate | Revoke is atomic and idempotent; the first transition owns the timestamp and audit event |
| P1 | API-key consistency | API service writes UUIDv4 while the model default is UUIDv7; `(project_id, org_id)`, role, name, and expiry validity lack database constraints | Service-local construction bypasses model identity policy; application validation is carrying database invariants | Database and application enforce the same identity, tenancy, role, name, and time constraints |
| P1 | API-key hot path | Authentication writes `last_used_at` on every request, including after a concurrent revoke, and mutates `updated_at`; no durable success/denied/expired use audit exists | Telemetry is coupled to the authentication transaction and lacks throttling/compare-state semantics | Authentication remains read-dominant; telemetry is throttled, state-aware, and independently observable |
| P1 | Encryption key lifecycle | `JOYSAFETER_VAULT_ENCRYPTION_KEY` protects Credential, repository token, and task identity material; `enc:v1` has no key ID; a syntactically valid wrong key passes startup | Ciphertext envelope and deployment configuration assume one timeless key | Ciphertexts identify their key; readers support an explicit keyring; startup verifies a database canary; rotation is resumable and rollback-safe |
| P1 | Task identity | Successful consume clears `encrypted_credential`, but expired, cancelled, or terminally failed unconsumed rows can retain it indefinitely | TTL controls consumption eligibility only; no terminal erasure worker exists | Every terminal path erases material, with retryable cleanup and measurable backlog |
| P1 | Repository token | Session archive/long retention preserves encrypted clone tokens; rotation exists but retention does not | Token lifetime is inherited implicitly from physical session lifetime | Repository token expiry/erasure is explicit and independent from session metadata retention |
| P1 | Audit retention | Credential access audit is append-only through UPDATE/DELETE triggers, has no retention mechanism, and contains actor/network PII | Immutability was implemented without an archival/deletion policy | Audit tamper resistance and finite retention coexist through partitioning or a privileged, logged purge boundary |
| P2 | Purge/reference integrity | Physical Credential/Group purge has no implementation; inactive relational references still block deletion and JSON snapshots can become dangling | Runtime dependency scans and physical reference reconciliation use different scopes; JSON history has no FK | Purge has a complete reference policy for live rows, tombstones, associations, and immutable snapshots |
| P2 | Query scaling | Active-key list uses the project-only index then sorts; a 20,000-row PostgreSQL probe scanned about 20,005 rows before top-N sorting | The query lacks a matching partial composite index | Active listing uses `(project_id, created_at DESC, id DESC) WHERE revoked_at IS NULL` or the final state-equivalent predicate |
| P2 | Naming/layout | Two `CredentialGroupService` classes, SQLAlchemy in a Domain invariant module, API mapping in Domain, 1,600+ line repository, 1,800+ line auth router, and a 500+ line API-key page obscure ownership | Historical migration accumulated facades and mixed responsibilities without a final removal pass | Names identify one responsibility; Domain is persistence/framework free; routes, application orchestration, and repositories are separately owned |
| P2 | Public/docs compatibility | `cnkey_`, `enc:v1`/`enc:`, `JOYSAFETER_VAULT_ENCRYPTION_KEY`, and `/api/v1/auth/api-keys` are real external/persisted contracts; `docs/api/openapi.md` also documents removed `/secrets` and `/vaults` surfaces | Internal cleanup and compatibility migration were not classified separately | Internal dead names are removed directly; external/deployed/persisted contracts use measured, time-bounded migrations |

### 11.4 Phase 1 encryption-key rotation closure (2026-08-23)

- Added `enc:v2:<key_id>:` writers and Python/Rust readers backed by `JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING` plus `JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID`.
- Bound the exact v2 prefix to the AES-GCM authentication tag as associated data in both languages; relabeling to a different configured key ID now fails even if both IDs contain identical key bytes. The unauthenticated pre-release v2 draft is not retained as a compatibility path.
- Added Python and Rust startup inventory checks that reject plaintext/unsupported envelopes and reject removal of `JOYSAFETER_VAULT_ENCRYPTION_KEY` or any v2 key ID while persisted material still references it.
- Preserved `enc:`/`enc:v1:` reads through `JOYSAFETER_VAULT_ENCRYPTION_KEY`; legacy-only deployments continue writing v1 until the staged switch.
- Replaced the internal `LegacyV1MaterialProtector` name and files atomically with `VersionedMaterialProtector`; no compatibility shim remains.
- Added migration `20260823_000005`, explicit canary initialization, fail-closed Python/Rust startup validation, bounded `FOR UPDATE SKIP LOCKED` rewrap, and envelope-only inventory. Online rewrap now rejects plaintext across Credential data, OAuth secret fields, Task Identity, and Repository Token storage instead of silently laundering the violation into ciphertext.
- Hardened the canary table itself: database constraints now enforce the same ASCII key-ID grammar as both runtimes, compare the prefix literally rather than with wildcard-bearing `LIKE`, and require a non-empty payload.
- Closed the missing-row initialization race with `INSERT ... ON CONFLICT DO NOTHING RETURNING`: concurrent initializers converge without overwriting the first committed canary, then decrypt and compare that winner. The whole initialization runs inside a savepoint, so a conflicting wrong-key winner cannot leave earlier keys from the same batch available for accidental outer-transaction commit.
- Hardened Python and Rust inventory scans against legacy/corrupt non-object JSONB. `data` and `oauth_config` arrays/scalars/null are now reported as `invalid-or-plaintext` rather than escaping as raw `jsonb_each_text` errors; online rewrap and repository read paths reject the same shapes without rewriting them to empty objects.
- Measured the startup inventory on disposable PostgreSQL 15 with 100,000 credentials and 300,000 v2 fields. The current parallel plan completed in about 1.24 seconds. A one-table-scan lateral rewrite was slower at about 2.92 seconds, so no speculative index, counter table, or query rewrite was introduced; the scan remains intentionally O(total persisted material).
- Confirmed the startup integrity boundary: startup inventory validates envelope syntax and key coverage but does not decrypt every business ciphertext. A syntactically valid active-key envelope with a damaged authentication tag is therefore not a startup failure and is skipped by rewrap because it already has the current prefix.
- Added a separate offline integrity verifier rather than expanding startup latency or availability risk. It runs in a PostgreSQL repeatable-read, read-only transaction; cursor-pages through Credential data, OAuth secret fields, Task Identity, and Repository Token storage; decrypts every non-empty current and historical envelope; reports only surface, record ID, field, and stable error category; and exits non-zero when any issue exists. Real PostgreSQL regression coverage proves current-key tag corruption is found on all four surfaces, pagination crosses one-row batch boundaries, malformed JSON is classified without rewrite, and the scan performs zero data writes.
- Wrapped each cross-store rewrap invocation in a savepoint; if a later store fails validation, earlier rewrites in the same batch are rolled back even when a caller catches the exception and commits its outer transaction.
- Real PostgreSQL migration upgrade/downgrade/upgrade passed at the single head `20260823_000005`. The final Python credential/lifecycle/reference matrix passed 343 tests, including the reverse-census closure, storage read-key coverage, strict canary constraints, plaintext rejection, and cross-store rollback behavior.
- A Python-generated AAD-bound v2 database canary was decrypted through Rust Managed Credential, Task Identity, and Repository Access adapters in one disposable PostgreSQL run. Rust versioned-envelope and embedded-contract tests passed, and the real-database `credential_runtime_contract` suite passed 279 tests serially; all disposable containers were stopped automatically.

### 11.2 Real PostgreSQL evidence

All probes ran against the disposable PostgreSQL database `joysafeter_api_key_audit_20260822`, migrated to head `20260822_000001`.

- API-key active-list plan with about 20,000 rows used `idx_cak_project`, scanned about 20,005 rows, and performed a top-N sort; observed execution was about 2.37 ms at this small scale.
- Duplicate API-key hashes caused `scalar_one_or_none()` authentication to raise `MultipleResultsFound`.
- A deleted Agent reference was omitted from the runtime dependency scan but still prevented physical Credential deletion through its FK.
- A terminated Session snapshot was omitted from the runtime scan and became a dangling JSON credential ID after physical deletion.
- A terminated Session group association was omitted from the runtime scan but still prevented physical Group deletion through its FK.
- Credential soft deletion retained ciphertext; group deletion retained every member ciphertext.
- Management projection returned `BASE_URL=https://user:password@...?token=secret` unchanged while masking a field named `TOKEN`.
- One corrupt Credential ciphertext raised `CredentialCiphertextError` and aborted the full management-list projection.
- Organization deletion reported no blocker for a deleted Credential or Group, then failed with an integrity error while deleting the project; the transaction rolled back and the organization remained.
- Direct DELETE of a credential access-audit probe row failed with `credential access audit rows are append-only`, proving there is currently no ordinary retention path.
- Archived-project API-key probe: legacy active-project write gate returned `PROJECT_ARCHIVED`; explicit project-admin gate allowed the archived project; `create_project_api_key` persisted exactly one row.

### 11.3 Reference and purge ordering

Physical cleanup cannot reuse the active-runtime dependency registry as-is. A safe purge coordinator must classify references independently of whether they are currently runnable:

1. Lock the target project/resource tombstone and establish a stable purge cutoff.
2. Erase remaining sensitive material before metadata deletion.
3. Reconcile Credential references from deleted Agents and Triggers, Environment JSON, Agent Version snapshots, and Session snapshots according to the approved historical-record policy.
4. Remove Session-to-Credential-Group association rows, including terminated sessions.
5. Purge Credential Group members in deterministic credential-ID order.
6. Purge the empty Credential Group.
7. Purge project-scoped API keys, repository tokens, task identity material, and other project-owned sensitive rows.
8. Delete project metadata only after a second physical-blocker check.
9. Delete organization metadata only after every project completes the same process.

Batch workers must be idempotent, use bounded batches, acquire locks in one documented order, use `FOR UPDATE SKIP LOCKED` only for independent queue claims, expose dry-run counts, persist failures without secret values, and resume after partial progress. A transaction must not claim a whole organization purge while performing unbounded work; orchestration state and per-project checkpoints are required.

### 11.4 Compatibility classification

- **Retain during migration:** `cnkey_` raw-key prefix, `/api/v1/auth/api-keys`, `JOYSAFETER_VAULT_ENCRYPTION_KEY`, `enc:v1`, and legacy `enc:` readers. These are externally stored, deployed, or persisted contracts.
- **Remove without compatibility shim:** unused `frontend/types/managed.ts::ApiKeyInfo`, the public plaintext `CredentialService.get_credential_data()` facade if production callsites remain zero, duplicate internal service names, stale no-`projectId` branches behind a permanent redirect, and obsolete internal imports.
- **Move to correct layer:** SQLAlchemy-backed Credential Group invariants to Infrastructure; Domain-to-`AppError` translation to Application/API; API-key schemas/routes out of the monolithic auth module; masking/projection persistence out of the oversized repository.
- **Correct documentation:** remove current-contract claims for deleted `/secrets`, `/vaults`, and `vault_ids`; document explicit project API-key routes, expiry/status semantics after implementation, and revoke rather than delete behavior.

### 11.5 Design gate

No production behavior should change until the lifecycle design defines:

- canonical states and precedence for API keys, Credentials, Groups, task identity records, repository tokens, and audit rows;
- transactional boundaries for revoke, secret erasure, tombstoning, and purge;
- historical JSON-reference handling and audit retention periods;
- keyring/envelope rollout and rollback floors;
- route convergence and compatibility-removal telemetry;
- migration preflight, dry-run, batching, observability, and rollback procedures.

### 11.6 Phase 0 implementation evidence

Implemented on 2026-08-23 after design approval:

- Explicit project API-key routes now reject archived projects through `require_joysafeter_project_admin`, matching the active-context write gate.
- API-key revoke is a conditional atomic transition with explicit `revoked`, `already_revoked`, and `not_found` outcomes. Replays preserve the first timestamp and do not emit duplicate transition audit rows.
- Organization deletion preflight counts Credential and Credential Group tombstones as physical blockers, preventing the previously reproduced late FK failure.
- Management masking no longer decrypts secret-classified fields. Display-safe fields are decrypted independently, malformed ciphertext degrades only that field to a mask, and displayed URLs discard user-info, query, and fragment components.
- API-key creation trims names and rejects blank input; generated IDs now use the model UUIDv7 default.
- Migration `20260823_000001` adds unique key hashes, project/organization composite integrity, role/name/expiry checks, and the active-list composite partial index.
- The migration deterministically preserves the oldest duplicate hash row and revokes/rekeys later duplicates. A real PostgreSQL upgrade from `20260822_000001` with two equal hashes completed with two historical rows, one original active hash, and one revoked duplicate; the disposable database was dropped afterward.

Verification:

- Alembic reports one head: `20260823_000001`.
- Phase 0 related suite: `87 passed, 65 warnings` against testcontainers PostgreSQL 15.
- Targeted Ruff checks passed.
- Repository-wide `git diff --check` remains non-zero only because the pre-existing modified file `backend/tests/test_documentation_contracts.py` has a trailing blank line at EOF; no Phase 0 file reports a whitespace error.
