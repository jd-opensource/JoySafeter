# Credential Actor Provenance and Service Boundary Design

**Date:** 2026-08-22
**Status:** Approved direction

## Goal

Make every credential mutation and material-use audit attributable to the initiating principal across HTTP, webhook, scheduler, Session, Trigger, Environment, Agent, and internal worker paths. Remove the remaining dynamic credential-service compatibility facades without changing public REST paths, existing error codes, typed identifiers, lock ordering, or persisted credential formats.

## Findings

### Correctly wired today

- Credential and Credential Group mutation routes construct `CredentialAuditActor` from `JoySafeterAuthContext` and the HTTP request.
- Environment credential mutations receive the request actor.
- Session and Task HTTP creation paths pass the request actor into credential-aware Session creation.
- Quickstart and Skill authoring material access records the authenticated principal.
- Public webhook secret verification records a `webhook_request` actor.
- Mutation audit writes share the business transaction; material-access audit writes use the dedicated append-only transaction.

### Broken provenance chain

`TriggerApplicationService` owns a credential audit actor, but `_fire_service()` does not pass it into `TriggerFireService`. `TriggerFireService` then creates `AgentTriggerExecutor` without actor context, and `AgentTriggerExecutor` creates `SessionCreationService` without actor context. The final `session.snapshot.created` event therefore falls back to `system/session_service` for:

- authenticated manual Trigger execution;
- authenticated webhook test execution;
- public webhook execution after successful authentication.

Scheduled Trigger execution is legitimately system-initiated, but currently receives the same implicit fallback rather than an explicit scheduler identity.

### Silent fallback risk

`compose_credential_application(audit_actor=None)` silently constructs `CredentialAuditActor.system("credential_application")`. Mutation-capable facades also accept an omitted actor. A new caller can therefore perform a write with syntactically valid but semantically false attribution.

### Historical service surface

`management_service.py` wraps the composed Application and forwards unknown attributes through `__getattr__`. `CredentialResourceService` repeats this pattern against the repository. This keeps historical method access working but hides the real Application interface, permits Infrastructure methods to leak through Application, and makes static verification of mutation boundaries unreliable.

### Incomplete audit payloads

- Credential Group membership events identify the Credential but not the owning Group.
- `CredentialAccessAuditEntry` carries complete actor data, but the access-audit table stores only `principal_type` and `principal_id`; `user_id`, `org_id`, `role`, IP address, and User-Agent are discarded.

## Architecture

### Explicit actor ownership

Every composition root must receive an explicit `CredentialAuditActor`. There is no implicit fallback inside `compose_credential_application`.

- HTTP routes use `credential_audit_actor(request, auth_ctx)`.
- Public webhook requests use an explicitly constructed `webhook_request` actor.
- Scheduler execution uses `CredentialAuditActor.system("trigger_scheduler")`.
- Internal validation-only adapters use a named system actor such as `agent_binding`; this is explicit even when no audit row is expected.
- Tests use `CredentialAuditActor.system("test")` unless they are verifying request attribution.

### Trigger propagation

Pass the actor through the complete chain:

```text
Trigger API / scheduler
  -> TriggerApplicationService
  -> TriggerFireService
  -> AgentTriggerExecutor
  -> SessionCreationService
  -> Credential snapshot audit
```

The initiating actor remains unchanged through the chain. Trigger ownership fields such as `trigger.user_id` remain business metadata and are not substituted for the authenticated caller.

### Explicit Credential Application API

Delete `management_service.py` after all callers migrate to the composed services. Remove both dynamic `__getattr__` implementations.

`CredentialResourceService` exposes explicit resource commands and queries used by API callers:

- `create`, `update`, `set_default`, `clear_default`, `archive`, `restore`, `soft_delete`;
- `get`, `get_or_raise`, `list`, `dependencies`;
- `get_masked` for response presentation.

Locking, encryption, decryption, and pending-impact primitives remain repository/UoW concerns and are accessed only by Application coordinators through declared ports. API modules do not call private methods.

`CredentialGroupService` remains the explicit group command/query service. Lifecycle-dependent archive/delete operations remain coordinated by `CredentialLifecycleCoordinator`; the composition result exposes named methods rather than a compatibility facade.

### Audit persistence

Complete the still-uncommitted `20260822_000001` creation of `joysafeter_credential_access_audits` with nullable columns:

- `user_id VARCHAR(255)`;
- `org_id VARCHAR(255)`;
- `role VARCHAR(32)`;
- `ip_address VARCHAR(255)`;
- `user_agent VARCHAR(1024)`.

The migration has not entered the repository baseline, so editing its table definition avoids creating fake migration history. Deployments upgrading through this work create the complete table atomically. Add an index on `(principal_type, principal_id, created_at)` for principal-oriented investigations. Existing unique runtime-success semantics remain unchanged.

Mutation audit continues to use `joysafeter_security_audit_logs` and its existing details contract. No schema rewrite or historical JSON backfill is required in this phase.

### Group membership attribution

Membership events keep `target_type="credential"` and `target_id=<credential_id>` for compatibility, and add `credential_group_id` to details. This preserves existing consumers while making the relationship transition reconstructable.

## Transaction and Failure Semantics

- Credential mutation plus mutation-audit row remains one transaction.
- Trigger Session snapshot creation plus snapshot-audit row remains one transaction.
- Credential material access audit remains append-only in its own transaction and remains fail-closed before material is returned.
- No new row locks are introduced and existing lock order is unchanged.
- Rollback must clear pending impacts and release all acquired locks.

## Compatibility

Preserve:

- `/credentials`, `/credential-groups`, `/triggers`, `/sessions`, and `/tasks` REST contracts;
- current event names and structured error codes;
- existing `principal_type` and `principal_id` values unless a caller was previously misattributed;
- typed IDs, credential ciphertext format, snapshot format, runtime generation, and lock order;
- nullable reads of historical access-audit rows.

Do not preserve:

- implicit generic system-actor fallback;
- `management_service.CredentialService` and `management_service.CredentialGroupService` compatibility facades;
- dynamic `__getattr__` forwarding from Application to Infrastructure;
- API calls to private Application methods;
- the `compatibility_after_commit` metric name.

## Verification

- Unit tests prove actor propagation through Trigger fire and Session snapshot creation.
- HTTP tests prove user and API-key attribution for Credential and Group mutations.
- PostgreSQL tests prove manual, test-webhook, public-webhook, and scheduler audit identities.
- Migration tests prove upgrade, existing-row null compatibility, inserts with full actor context, index creation, and downgrade.
- Architecture tests reject optional actor composition, dynamic service forwarding, old facade imports, and the deleted facade file.
- Credential, Group, Environment, Session, Trigger, access-audit, migration, and dependency-boundary suites run against real PostgreSQL.
- Ruff, format, compileall, migration-head validation, `git diff --check`, cache removal, and isolated database cleanup complete the gate.
