# Credential Domain Closure — v1 Freeze Design

**Date:** 2026-08-19  
**Status:** Approved for implementation  
**Supersedes:** The E2/E3 writer-cutover, backfill, and release requirements in `2026-08-16-credential-domain-closure-p0-5-design.md`

## 1. Decision

Credential Domain Closure completes without a persistence-format migration.

- `legacy-v0` remains read compatibility only.
- `v1` is the only supported production persistence write format.
- `v2` remains a fail-closed read-compatibility grammar and test contract; no production writer flag or rollout is introduced.
- Live Environment rows and immutable Agent Version / Session Snapshots are not backfilled.
- Closure is defined by domain authority, lifecycle correctness, material isolation, and canonical public language—not by renaming stored JSON keys.

## 2. Production Outcomes

Closure is complete only when all of the following are true:

1. Credential Domain Core has no imports from API, Application, Infrastructure, Shared application modules, Pydantic, SQLAlchemy, Redis, or HTTP clients.
2. The reference machine contract and every production dependency scanner execute one consistent schema/path grammar.
3. Dependency Registry is the only lifecycle authority in `enforce` mode; legacy scanners run only in explicit `shadow` rollback/observation mode.
4. Managed Credential material cannot reach sandbox-visible env, files, argv, logs, Audit, or Snapshot, except explicit Environment Injection into env.
5. Public Backend and Frontend contracts use Credential language: `CredentialGroup`, `environment_credential_ids`, and `credential_field`.
6. Legacy `Vault`, `secret_refs`, and `secret_key` names remain only in exact compatibility adapters, persisted v1 encoding, migrations, and compatibility fixtures.
7. All production writers call the v1 Codec explicitly or use a v1-only persistence adapter.

## 3. Slice A — Architecture and Registry Contract Closure

Domain Core validates and stores domain IDs without importing `joysafeter_shared.ids`. Public EntityId parsing belongs to API/Application adapters.

The machine contract is the normative persisted-reference grammar. Registry integration tests build complete valid documents for each `(document, path, schema)` case, including required sibling fields and schema-specific alias legality.

Explicit-v2 records containing legacy aliases are corrupt and fail closed. Unknown explicit schemas fail closed with a stable error classification.

## 4. Slice B — Dependency Registry Authority

- `shadow`: run legacy and Registry scans concurrently; legacy result is authoritative; Registry differences are safe metadata-only telemetry.
- `enforce`: run only Registry scanners for lifecycle decisions. Legacy scanners are not called and cannot fail or block the operation.

`enforce` is the default for new deployments after the full closure test suite passes. `shadow` remains an explicit rollback setting.

Resource and Group archive/delete use operation-specific dispositions. Scanner failure in `enforce` fails closed. A blocker returns stable public dependency IDs and never material or raw JSON.

## 5. Slice C — Canonical Public Language with v1 Storage

Environment request decoders accept canonical and legacy aliases, normalize immediately to canonical Application values, and reject conflicting aliases.

Backend responses emit canonical keys only:

- `environment_credential_ids`
- `credential_field`
- `service_credential_id`

The persistence adapter then encodes those canonical values to v1 JSON keys. Stored rows may still contain `secret_refs` and `secret_key`; API callers do not see those names.

Frontend domain types and active components use `CredentialGroup`, `CredentialGroupCredential`, `environment_credential_ids`, and `credential_field`.

Legacy `/managed/vaults` routes may remain only as redirects. Legacy response parsers may remain only as compatibility re-exports with architecture-test ownership and a removal condition.

## 6. Slice D — Runtime Material Boundary and Final Gates

One integration suite proves the material boundary for model inference, MCP egress, HTTP bearer/header/cookie egress, webhook verification, Repository Access, Task Identity, and explicit Environment Injection.

Only Environment Injection may place selected material in sandbox env. Other material must be absent from sandbox env, mounted files, argv, logs, Audit details, and persisted Snapshot JSON.

Final gates include Backend architecture/regression suites, complete Rust tests, Frontend tests/type-check/lint, terminology census, diff checks, and a release evidence document.

## 7. Explicitly Cancelled Work

The following are not part of Credential Domain Closure:

- `CREDENTIAL_REFERENCE_WRITE_VERSION`;
- production v2 writes;
- live Environment reference backfill;
- legacy-key count reaching zero;
- immutable Snapshot rewrite;
- enc:v2, AAD, HKDF, Keyring, or full-database re-encryption;
- fixed-duration 24-hour/288-sample migration evidence.

## 8. Cleanup Standard

Completion requires removing dead aliases, duplicate scanners, unused exports, obsolete E2/E3 runbooks, generated review packages that are not release evidence, and unowned compatibility exceptions. Compatibility code must live in named boundary modules and be protected by exact architecture tests.

