# Credential Public-ID Normalization — Design

## Problem

Migration `20260814_000001_unify_credentials` moved credential references from
names to identifiers, but `_credential_id_for()` serialized PostgreSQL UUID
values with `str(row[0])`. JSONB references therefore contain bare UUIDs while
the public identifier contract requires `cred_<uuid>`.

The same migration validated those JSONB references against a set of bare UUID
strings, so its completion gate accepted the malformed representation. Its
session-snapshot regression test also records a bare UUID as the expected
result.

Confirmed preproduction data contains bare UUIDs in
`joysafeter_environments.config.egress_services[].service_credential_id`.

## Canonical Invariant

Database FK columns continue storing native UUID values. Every credential ID
persisted inside JSONB or exposed through an API must be the canonical public
form:

```text
cred_<uuid>
```

No runtime API or global `CredentialId` parser accepts bare UUIDs.

## Affected Stores

The repair covers all credential references persisted in JSONB:

1. `joysafeter_environments.config.secret_refs[]`
2. `joysafeter_environments.config.egress_services[].service_credential_id`
3. `joysafeter_sessions.agent_snapshot.model_credential_id`
4. `joysafeter_sessions.agent_snapshot.environment.config.secret_refs[]`
5. `joysafeter_sessions.agent_snapshot.environment.config.egress_services[].service_credential_id`
6. `joysafeter_agent_versions.snapshot.model_credential_id`
7. Legacy `joysafeter_agent_versions.snapshot.secret_ref`
8. Legacy `joysafeter_sessions.agent_snapshot.secret_ref`, if any survived

## Reference Generations

- **G0 legacy name:** `secret_ref` contains a credential name.
- **G1 bare UUID:** `019f...` without an entity prefix.
- **G2 canonical public ID:** `cred_019f...`.
- **Invalid:** malformed values, missing credentials, cross-project references,
  wrong credential kinds, archived/deleted credentials where a live reference
  is required, or ambiguous legacy names.

The migration converts G0/G1 to G2, preserves validated G2 values, and aborts
on Invalid values.

## Migration

Add revision `20260815_000002` after `20260815_000001`. Do not edit the already
published `20260814_000001` revision.

The migration is online-only, irreversible, and transactional:

1. Lock all candidate environment, session, and agent-version rows.
2. Read the credential catalog needed to validate references.
3. Classify and validate every reference without issuing updates.
4. Abort with owner/path/value diagnostics if any reference is invalid.
5. Apply all prepared JSONB updates only after preflight succeeds.

Validation rules:

- Environment and frozen-environment references require a live, same-project
  `kind='service'` credential.
- Model snapshot references require a same-project `kind='model'` credential.
- Legacy names must resolve to exactly one live same-project credential of the
  required kind.
- Null/empty optional model references remain absent.
- Unknown keys and unrelated JSON content are preserved byte-for-byte at the
  semantic JSON level.

## Runtime Hardening

### Backend

- Request `CredentialId` validation remains strict.
- Persisted-data `PydanticValidationError` must not be reported as user
  `fix_input`; it is an internal persisted-data failure.
- Credential dependency scans continue comparing canonical IDs and gain
  regression coverage for repaired environment/session snapshots.

### Rust

- Invalid persisted credential IDs must return contextual errors rather than be
  silently ignored.
- A present but malformed `model_credential_id` is corruption, not an explicit
  request to remove the model credential.
- External egress construction must surface an invalid credential reference
  instead of silently omitting the route.

### Frontend

- `EnvironmentConfig.secret_refs` is `CredentialId[]`.
- The environment response parser validates nested `secret_refs[]` and
  `egress_services[].service_credential_id` values.

## Rollout

1. Take and verify a database backup.
2. Stop API, worker, orchestrator, and old HA writers.
3. Run the migration preflight through `alembic upgrade head`.
4. Confirm head `20260815_000002`.
5. Run a structural query proving every credential JSON reference is canonical.
6. Start one API/orchestrator instance.
7. Verify environment list/detail, representative model execution, and external
   egress credential injection before scaling out.

## Out of Scope

- Changing native UUID FK columns.
- Globally accepting bare UUIDs in `CredentialId`.
- Re-encrypting credential values.
- Modifying concurrent identity-federation work.
