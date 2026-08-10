# Secret Reference ID Migration Design

**Status:** Proposed and approved for implementation planning  
**Date:** 2026-08-10  
**Base:** Credential Domain Normalization Phase 1  
**Target:** Zero-downtime migration from name-based Secret references to semantic ID references

## 1. Problem Statement

JoySafeter currently gives every Secret resource a stable ID, but persisted consumers reference it by mutable name:

- Agent stores `secret_ref`.
- Trigger stores `secret_ref` and `secret_key`.
- Environment stores `secret_refs` and `egress_services[].credential_ref` inside JSON configuration.
- Quickstart and Skill Authoring requests resolve `secret_ref` by project-scoped name.
- Python and Rust runtime paths load Secret data by exact name.

This design has four structural defects:

1. Renaming a Secret can leave persisted references stale.
2. Delete and rename checks are application-level check-then-write operations and therefore vulnerable to TOCTOU races.
3. A string named `secret_ref` has different business meanings across model configuration, outbound authentication, and Webhook authentication.
4. Names are being used as identity even though they are intended to be mutable display attributes.

Phase 1 added canonical names, validation, lifecycle blockers, and selector safety. Those protections remain useful but cannot provide database-backed referential integrity. Phase 2 replaces persisted name identity with stable semantic ID references.

## 2. Goals

1. Persist every Agent, Environment, Egress, and Trigger credential reference by stable resource ID.
2. Remove runtime name lookup after the migration cutover.
3. Preserve zero-downtime deployment through an expand, backfill, verify, and cutover sequence.
4. Allow old clients to submit legacy name fields during the compatibility release while immediately resolving them to IDs.
5. Stop writing and reading persisted name references after cutover in the same release.
6. Retain old name fields for one release only as rollback snapshots, then remove them in the following release.
7. Eliminate rename and delete TOCTOU races through transactional row locking and database-backed binding records.
8. Preserve project isolation, Secret masking, historical OAuth compatibility, and existing route paths.
9. Use business-semantic public field names rather than exposing a generic `secret_id` everywhere.

## 3. Non-Goals

1. Renaming the existing `joysafeter_secrets` table.
2. Merging Project Access Tokens, MCP Credential Sets, and Secret resources into one database aggregate.
3. Giving Credential Fields their own resource IDs.
4. Implementing OAuth creation or authorization flows.
5. Removing legacy fields in the compatibility release.
6. Replacing all JSON configuration with fully normalized relational models.

## 4. Domain Vocabulary

### 4.1 Credential Resource

The existing Secret aggregate is treated internally as a Credential Resource. Its stable ID remains the existing `secret_...` entity ID.

### 4.2 Model Connection

A Credential Resource with an LLM-compatible kind, provider, and protocol. It supplies model endpoint and provider authentication configuration.

Used by:

- Agent
- Quickstart
- Skill Authoring

### 4.3 Service Credential

A Generic Credential Resource containing fields used for external service or Webhook authentication.

Used by:

- Environment direct injection
- Environment Egress authentication
- Webhook Trigger authentication

### 4.4 Credential Field

A named field inside a Credential Resource, such as `OPENAI_API_KEY`, `WEBHOOK_SECRET`, or `COOKIE_HEADER`. A Credential Field is not an independent resource and does not receive a separate ID.

### 4.5 Excluded Aggregates

- Project Access Token remains the external-project API authentication resource.
- MCP Credential Set remains the Vault aggregate referenced by `vault_id`.

## 5. Semantic Public Interfaces

The API must express the business role of a referenced Credential Resource.

### 5.1 Agent

```json
{
  "model_connection_id": "secret_..."
}
```

Legacy compatibility input:

```json
{
  "secret_ref": "openai-production"
}
```

### 5.2 Quickstart and Skill Authoring

```json
{
  "model_connection_id": "secret_..."
}
```

### 5.3 Webhook Trigger

```json
{
  "service_credential_id": "secret_...",
  "credential_field": "WEBHOOK_SECRET"
}
```

### 5.4 Environment Direct Injection

```json
{
  "service_credential_ids": ["secret_..."]
}
```

### 5.5 Environment Egress

```json
{
  "service_credential_id": "secret_...",
  "credential_field": "API_TOKEN",
  "authentication_method": "bearer"
}
```

### 5.6 Compatibility Conflict Rules

During the compatibility release, a request may contain a new ID field, a legacy name field, or both.

- ID only: validate and use the ID.
- Legacy name only: resolve within the current project and use the resulting ID.
- Both resolve to the same resource: accept.
- Both resolve to different resources: reject with `CREDENTIAL_REFERENCE_CONFLICT`.
- Neither supplied where required: reject with the purpose-specific required-field error.

Legacy name input is an API adapter concern. It must never become the persisted or runtime identity after cutover.

## 6. Semantic Type System

Python, TypeScript, and Rust must expose distinct semantic types even though their serialized representation is the same entity ID format.

```text
CredentialResourceId
├── ModelConnectionId
└── ServiceCredentialId
```

Required validation:

- `ModelConnectionId` must reference an active LLM-compatible resource.
- `ServiceCredentialId` must reference an active Generic resource.
- The referenced resource must belong to the current project.
- A required Credential Field must exist.
- Authentication-specific field values must satisfy runtime rules, such as nonblank Webhook credentials.

## 7. Persisted Owner Model

### 7.1 Agent

Add nullable `model_connection_id` to the Agent persistence model and database table.

- New writes persist `model_connection_id`.
- Legacy `secret_ref` remains for one compatibility release as a rollback snapshot.
- Runtime reads only `model_connection_id` after cutover.

### 7.2 Trigger

Add nullable `service_credential_id` to the Trigger table.

- Keep `secret_key` during migration but expose it publicly as `credential_field`.
- Legacy `secret_ref` remains for one release as a rollback snapshot.

### 7.3 Environment

Add ID references to the existing JSON configuration:

```json
{
  "service_credential_ids": ["secret_..."],
  "egress_services": [
    {
      "service_credential_id": "secret_...",
      "credential_field": "API_TOKEN"
    }
  ]
}
```

Legacy `secret_refs` and `credential_ref` remain for one release but become rollback-only after cutover.

### 7.4 Stable Egress Slot Identity

Every persisted Egress service must have a stable service ID. Binding identity must not depend on an array index because reordering the array must not create a different logical binding.

## 8. Credential Binding Projection

Create `joysafeter_credential_bindings`.

### 8.1 Columns

```text
id
project_id
credential_id
consumer_type
consumer_id
binding_purpose
binding_slot
created_at
updated_at
```

### 8.2 Consumer Types

- `agent`
- `environment`
- `trigger`

### 8.3 Binding Purposes

- `agent_model_connection`
- `environment_injected_credential`
- `environment_egress_authentication`
- `trigger_webhook_authentication`

### 8.4 Binding Slot

- Agent model binding: `model`
- Trigger Webhook binding: `webhook`
- Environment direct binding: the Credential Resource ID
- Environment Egress binding: the stable Egress service ID

### 8.5 Constraints

- Foreign key from `credential_id` to the existing Secret ID with physical delete restricted.
- Composite project/credential constraint prevents cross-project binding.
- Unique constraint on `(consumer_type, consumer_id, binding_purpose, binding_slot)`.
- Index on `(project_id, credential_id)` for dependency queries.
- Index on `(consumer_type, consumer_id)` for projection replacement.

## 9. Single Source of Truth

Owner semantic configuration is the business source of truth. The Binding table is a transactionally generated integrity projection and dependency index.

Binding rows:

- cannot be edited through a public API;
- are generated from the final validated Owner configuration;
- are completely replaced for an Owner inside the same transaction as the Owner update;
- must exactly equal the reference set present in the Owner configuration.

This prevents Owner configuration and Binding rows from becoming independent, conflicting sources.

## 10. Transactional Mutation Protocol

### 10.1 Owner Create or Update

1. Parse semantic ID fields and compatibility name fields.
2. Resolve all compatibility names to IDs.
3. Reject ID/name conflicts.
4. Lock all referenced Credential Resource rows in stable ID order.
5. Validate project, kind, deletion status, fields, and purpose-specific requirements.
6. Persist the Owner's final semantic ID configuration.
7. Delete the Owner's previous Binding rows.
8. Insert the complete new Binding projection.
9. Verify the projected Binding set equals the final Owner reference set.
10. Commit.

Stable lock ordering prevents deadlocks when one Owner references multiple credentials.

### 10.2 Secret Rename

Rename changes only the display name. No Owner configuration or Binding row changes.

### 10.3 Secret Soft Delete

1. Lock the Credential Resource row with `FOR UPDATE`.
2. Query active Binding rows.
3. Reject when any Binding exists.
4. Set `deleted_at` only when the Binding set is empty.
5. Commit.

Owner binding creation locks the same Credential Resource row before inserting the Binding. This serializes binding creation with soft deletion and removes the current TOCTOU race.

### 10.4 Physical Delete

The database foreign key blocks physical deletion while Binding rows exist.

## 11. Core Invariants

1. Credential Resource IDs are immutable.
2. Names are mutable display and search attributes only.
3. Every persisted reference uses an ID after cutover.
4. Every persisted reference has exactly one corresponding Binding row.
5. Every Binding belongs to the same project as its consumer and Credential Resource.
6. Model Connection purposes reference only LLM-compatible resources.
7. Service Credential purposes reference only Generic resources.
8. Binding rows never point to soft-deleted resources.
9. Owner mutation and Binding replacement are atomic.
10. Secret rename never requires reference rewriting.
11. Secret soft delete and binding creation serialize on the Secret row lock.
12. Credential values remain encrypted and are resolved only at execution boundaries.
13. IDs, names, and field names may appear in audit metadata; credential values may not.
14. Legacy names are never consulted by runtime code after ID-only cutover.

## 12. Architecture Components

### 12.1 CredentialReferenceResolver

Responsibilities:

- resolve compatibility name input to ID;
- validate ID format;
- validate project ownership;
- validate Credential Resource kind;
- validate deletion state;
- validate required Credential Fields;
- detect ID/name conflicts.

### 12.2 CredentialBindingProjector

Responsibilities:

- extract semantic references from Agent, Environment, and Trigger final configurations;
- produce deterministic Binding rows;
- replace the complete Binding set transactionally;
- verify projection equality.

### 12.3 CredentialDependencyService

Responsibilities:

- query only the Binding table;
- return stable, sorted dependency categories and consumer IDs;
- support deletion, archive policy, audit, and user-facing dependency errors.

### 12.4 CredentialValueResolver

Responsibilities:

- load active Credential Resource data by ID;
- decrypt only the requested field or purpose-required fields;
- enforce runtime rules such as nonblank Webhook values;
- never emit plaintext through logs or error data.

### 12.5 Rust CredentialStore

Responsibilities:

- accept only Credential Resource IDs after cutover;
- query Secret data by ID and project;
- reject soft-deleted or cross-project resources;
- remove all runtime name-lookup paths after cutover.

### 12.6 Frontend Selectors

- option value is always the resource ID;
- visible label is the resource name;
- unavailable historical selections remain visible during compatibility editing;
- Credential Field options come from metadata keys;
- selectors never fetch plaintext `secret_data`.

## 13. Error Contract

New shared errors:

- `CREDENTIAL_REFERENCE_CONFLICT`
- `MODEL_CONNECTION_ID_REQUIRED`
- `MODEL_CONNECTION_NOT_FOUND`
- `MODEL_CONNECTION_KIND_INVALID`
- `SERVICE_CREDENTIAL_ID_REQUIRED`
- `SERVICE_CREDENTIAL_NOT_FOUND`
- `SERVICE_CREDENTIAL_KIND_INVALID`
- `CREDENTIAL_FIELD_NOT_FOUND`
- `CREDENTIAL_FIELD_VALUE_BLANK`
- `CREDENTIAL_BINDING_INCOMPLETE`
- `CREDENTIAL_BINDING_PROJECT_MISMATCH`
- `CREDENTIAL_BACKFILL_UNRESOLVED`

Public Webhook routes must sanitize all Credential resolution errors to the existing generic unauthorized response.

## 14. Zero-Downtime Migration

### 14.1 Expand

Add:

- Agent `model_connection_id`;
- Trigger `service_credential_id`;
- Environment ID fields in schemas;
- stable Egress service IDs;
- `joysafeter_credential_bindings`;
- indexes and non-destructive constraints.

Do not remove legacy fields.

### 14.2 Compatibility Deployment

Deploy code that:

- reads ID first and legacy name only as fallback;
- accepts both new ID and legacy name API inputs;
- resolves legacy names immediately to IDs;
- writes ID fields and Binding rows;
- temporarily maintains legacy name snapshots for rollback;
- supports both Python and Rust compatibility modes.

### 14.3 Online Backfill

Backfill in deterministic batches by project and consumer type.

For each legacy reference:

1. normalize the legacy name;
2. resolve by `(project_id, normalized_name)`;
3. validate expected resource kind;
4. write the semantic ID field;
5. generate the Binding row;
6. record the migration result.

Never guess when resolution is missing or ambiguous. Record unresolved items for explicit repair.

### 14.4 Cutover Gate

ID-only cutover requires:

- zero unresolved active references;
- every Owner reference represented by one Binding;
- every Binding represented by one Owner reference;
- no cross-project Binding;
- no Binding to deleted resources;
- Python and Rust resolution parity;
- successful concurrent bind/delete tests;
- zero legacy-name runtime fallback during the observation window.

### 14.5 ID-Only Cutover

Enable `SECRET_REFERENCE_MODE=id_only`.

After cutover:

- runtime reads IDs only;
- new writes stop updating legacy name snapshots;
- old API clients may still send names, but the API adapter resolves them to IDs before entering domain services;
- domain services reject name-only internal calls;
- Binding table becomes the only dependency query source.

### 14.6 Contract Release

In the following release:

- remove legacy database columns and JSON fields;
- remove name fallback and compatibility serializers;
- remove the migration feature flag;
- remove legacy-name tests;
- retain audit history and migration reports.

## 15. Rollback

Before the Contract release:

- disable `id_only` mode;
- return to ID-first/name-fallback reads;
- retain all ID fields and Binding rows;
- resume temporary legacy snapshot writes only if rollback requires them.

Rollback must not delete ID or Binding data. The Contract release is the point after which fast rollback to name-based runtime is no longer supported.

## 16. Observability

Required metrics:

- references discovered by consumer type and purpose;
- references successfully backfilled;
- unresolved names;
- kind mismatches;
- cross-project mismatches;
- Binding projection mismatches;
- compatibility name resolutions;
- runtime name-fallback hits;
- ID-only resolution failures;
- bind/delete lock contention;
- backfill batch duration and retry count.

Required structured audit events:

- `credential_reference.backfilled`
- `credential_reference.unresolved`
- `credential_reference.conflict`
- `credential_binding.rebuilt`
- `credential_reference.cutover_enabled`
- `credential_reference.rollback_enabled`

No event may include decrypted credential values.

## 17. Backfill Idempotency

- Backfill is restartable.
- A successfully migrated Owner can be processed again without changing its semantic result.
- Existing correct ID fields are validated, not overwritten blindly.
- Binding replacement is deterministic.
- Every batch records a high-water mark and result counts.
- Failed rows remain retryable after explicit data repair.

## 18. Testing Strategy

### 18.1 Unit and Contract Tests

- semantic ID parsing and branded types;
- name-to-ID compatibility resolution;
- ID/name conflict behavior;
- kind validation by purpose;
- Credential Field validation;
- deterministic Binding projection;
- stable dependency ordering;
- legacy serializer deprecation behavior.

### 18.2 Migration Tests

- complete backfill for every consumer type;
- unresolved names;
- ambiguous historical names;
- deleted credentials;
- cross-project collisions;
- idempotent reruns;
- mixed already-migrated and legacy records;
- rollback-mode reads.

### 18.3 Concurrency Tests

- Secret delete racing with new Agent binding;
- Secret delete racing with Trigger update;
- Environment update racing with Secret delete;
- two Owners binding the same Secret;
- Owner rebinding between two Secrets;
- stable lock ordering with multiple credentials.

### 18.4 Python and Rust Parity

- identical ID resolution;
- identical project and deletion filtering;
- identical Environment direct and Egress extraction;
- identical field-value results;
- no runtime name lookup after cutover.

### 18.5 Frontend Tests

- selector wire values are IDs;
- labels remain names;
- unavailable IDs remain visible but invalid;
- old name payloads are adapted during compatibility mode;
- ID/name conflicts block save;
- no plaintext fetch;
- Trigger and Environment field selection uses metadata only.

## 19. Security Properties

- IDs are not authorization; every lookup remains project-scoped.
- Composite project validation prevents cross-project ID reuse.
- Credential values remain encrypted at rest.
- Binding rows contain no Credential Field values.
- Public Webhook errors remain generic.
- Empty authentication values remain invalid.
- Soft-deleted credentials cannot receive new bindings.
- Physical delete cannot bypass Binding foreign keys.

## 20. Acceptance Criteria

1. Agent, Environment, Egress, and Trigger persisted references use semantic IDs.
2. Runtime Python and Rust paths perform no name-based Credential lookup in ID-only mode.
3. Secret rename requires no reference updates and cannot break consumers.
4. Binding creation and Secret soft delete cannot produce a dangling reference under concurrency.
5. Physical deletion is blocked by database constraints while Bindings exist.
6. Old clients can submit legacy names during the compatibility release.
7. Legacy names are not persisted or read by domain/runtime code after cutover.
8. Backfill reports zero unresolved active references before cutover.
9. Binding projection exactly matches Owner semantic ID configuration.
10. Project, kind, deletion, and Credential Field validation are consistent across Python and Rust.
11. Frontend selector values are IDs and visible labels are names.
12. No migration, API response, log, or error exposes plaintext credential values.
13. Rollback to compatibility mode remains available until the following Contract release.

