# Credential Envelope Unification (A+B+C) — Revised Design

- **Date:** 2026-08-15
- **Status:** Approved for implementation after production-data review
- **Target branch / worktree:** `joysafeter-v2-0814` (`.worktrees/joysafeter-v2-0814`)
- **Related:** enc:v1 commit `d0c59322b`, fail-closed commit `bf9bee70e`, migration `20260814_000001_unify_credentials`
- **Production fact:** the `JOYSAFETER_VAULT_ENCRYPTION_KEY` used by `joysafeter-v2-ha` and `joysafeter-v2-0814` is unchanged

## Problem

Deploying `joysafeter-v2-0814` over production data originating on
`joysafeter-v2-ha` produces repeated
`CredentialCiphertextError: Stored credential is not encrypted` responses on
credential reads.

The failure is caused by two independent data incompatibilities plus one reader
inconsistency:

1. The envelope prefix changed from `enc:` to `enc:v1:` while the AES-GCM
   payload remained byte-identical: standard base64 of
   `nonce[12] + ciphertext_with_tag`.
2. `20260814_000001_unify_credentials` copied encrypted and plaintext legacy
   values verbatim. It copied `joysafeter_secrets.data`, MCP `token_value`, and
   `oauth_config` without normalizing their envelopes.
3. Python rejects every value that is not `enc:v1:`, while Rust currently
   passes every non-`enc:v1:` value through unchanged.

Production inspection confirmed at least:

- **G1 plaintext:** model configuration, API-key, base-URL, and auth-token
  values with no `enc:` prefix.
- **G2 legacy envelope:** `enc:` values copied from HA.
- **G3 current envelope:** `enc:v1:` values written by 0814 may coexist with
  G1 and G2.

Consequences on the deployed code:

| Data | Python credential reads | Rust runtime injection |
|---|---|---|
| G1 plaintext | fails closed with a 500 | injects plaintext, leaving data insecure at rest |
| G2 bare `enc:` | fails closed with a 500 | injects the ciphertext string as the credential |
| G3 `enc:v1:` | decrypts | decrypts |

Fixing only G2 is insufficient: confirmed G1 rows would continue to fail.

## Core Invariant

> Writers emit only the current envelope (`enc:v1:`). Readers accept every
> explicitly supported envelope version (`enc:v1:` and transitional bare
> `enc:` interpreted as v1). Unknown envelopes, plaintext non-empty values,
> malformed ciphertext, and non-string credential values fail closed. Empty
> strings are the sole unencrypted sentinel and mean “credential absent”.

At-rest stores must contain only:

- valid `enc:v1:` strings; or
- an empty string where the domain explicitly permits an absent credential.

Every non-empty ciphertext must decrypt successfully with the configured vault
key. A prefix-only database check is not sufficient.

## Shared Envelope Definition

The envelope policy is currently duplicated or partially reimplemented in four
places:

1. Python `CredentialCipher` accepts only `enc:v1:`.
2. Python `agent_identity_capture._encrypt` emits `enc:v1:` inline.
3. Rust `VaultCipher::decrypt_or_passthrough` decrypts `enc:v1:` but passes
   everything else through.
4. Rust agent-identity decoding separately hard-codes
   `starts_with("enc:v1:")` before calling the cipher.

The revised design centralizes policy once per language:

- `CURRENT = "enc:v1:"`.
- Supported reads are `enc:v1:` and transitional bare `enc:`.
- Payload format is standard base64 of
  `nonce[12] + AES-256-GCM(ciphertext + tag)`.
- Empty string returns the empty sentinel without attempting decryption.
- Non-empty plaintext raises a typed ciphertext error.
- Unknown versioned envelopes such as `enc:v2:` raise an unsupported-envelope
  error until that version is explicitly implemented.
- Python identity capture uses `CredentialCipher.encrypt`.
- Rust callers, including agent identity, call the shared envelope decoder and
  do not perform local prefix checks.

## Part A — Atomic Data Normalization

Create a new Alembic revision after `20260814_000002`; do not edit the already
applied and irreversible `20260814_000001_unify_credentials` revision.

### Stores in scope

1. Every value in `joysafeter_credentials.data`, including archived and
   soft-deleted rows.
2. `joysafeter_credentials.oauth_config.client_secret` and
   `joysafeter_credentials.oauth_config.refresh_token` when present.
3. `joysafeter_session_repo.encrypted_token`.
4. `joysafeter_task_identity_contexts.encrypted_credential` is audited and
   cryptographically verified. It is not expected to contain HA legacy data,
   but it must not be omitted from the global invariant.

### Classification

Each stored value is classified without coercing its JSON type:

- **EMPTY:** empty string; preserved.
- **G3:** starts with `enc:v1:`; decrypt and verify, then preserve.
- **G2:** starts with bare `enc:`; interpret the payload as v1, decrypt and
  verify, then replace only the prefix with `enc:v1:`.
- **G1:** non-empty string with no recognized envelope; encrypt with the current
  vault key.
- **UNKNOWN:** an unsupported versioned envelope such as `enc:v2:`; abort.
- **NON_STRING:** a credential value that is not a JSON string; abort.
- **CORRUPT:** recognized envelope with invalid base64, insufficient payload,
  invalid UTF-8, authentication failure, or wrong key; abort.

A plaintext value that happens to begin with `enc:` is deliberately treated as
ambiguous ciphertext and causes a validation failure rather than being silently
re-encrypted.

### Full preflight

The migration must load the configured `JOYSAFETER_VAULT_ENCRYPTION_KEY` and
validate every non-empty G2 and G3 value before changing any row. One successful
sample is not sufficient because production may contain corrupt rows or data
from multiple historical keys.

The operator has confirmed that the environment key did not change across the
HA-to-0814 upgrade. The full cryptographic preflight remains authoritative and
must abort on any mismatch.

If the database contains only G1 values and no ciphertext anchor, the configured
key becomes the authoritative key after normalization. This condition is
reported explicitly.

### Atomicity and concurrency

- The migration is online-mode only.
- Validation and mutation run inside Alembic’s PostgreSQL transaction with no
  internal commit.
- Any validation or write error rolls back the entire revision.
- Credential-writing API, worker, orchestrator, and old HA instances must be
  stopped or placed behind an explicit write freeze before preflight begins.
- No old writer may remain able to emit new bare `enc:` data between the final
  scan and traffic restoration.

### Idempotency

The normalization helpers are idempotent:

- G3 remains byte-for-byte unchanged.
- G2 becomes G3 once.
- G1 becomes G3 once.
- Re-running the helper over normalized rows produces no changes.

Alembic itself records the revision once; idempotency is tested by invoking the
normalization helper twice in the same test database.

## Part B — Compatibility Readers and Consolidation

### Python

- `CredentialCipher.decrypt_stored` accepts G2 and G3.
- `CredentialCipher.decrypt_stored("")` returns `""`.
- Non-empty plaintext and unknown envelopes fail closed.
- Credential services reject non-string stored values instead of coercing them
  with `str()`.
- Agent identity capture delegates encryption to `CredentialCipher`.

### Rust

- Replace `decrypt_or_passthrough` with a fail-closed shared envelope decoder.
- Accept G2 and G3, return the empty sentinel, and reject non-empty plaintext.
- Remove the agent-identity `enc:v1:` pre-check.
- Ensure all credential-data, MCP-token, repo-token, environment-secret, and
  identity paths use the same decoder.

Cross-language fixtures cover every supported envelope version and prove that
Python and Rust decrypt identical payloads.

## Part C — Rust Fail-Closed Activation

Part C is a separate rollout gate, even if the code lands in the same source
change:

1. Ship Part A and Part B.
2. Run the normalization migration while credential writes are frozen.
3. Run the exact structural and cryptographic invariants.
4. Restore traffic with compatibility readers.
5. Enable or deploy Rust fail-closed behavior only after every environment has
   passed the invariant.

If operational packaging cannot separate B and C, Rust hardening must be behind
an explicit configuration gate that remains disabled until normalization is
verified.

After activation, residual plaintext or corrupt ciphertext causes the existing
build/session failure path with a clear credential-decryption error. Empty or
absent credentials continue to skip injection.

## Verification

### Structural invariant

For `joysafeter_credentials.data`, use `jsonb_each`, not `jsonb_each_text`, so
non-string values are not silently coerced. The invariant fails if any value is:

- non-string;
- non-empty and not `enc:v1:`; or
- an unsupported envelope.

Equivalent checks apply to the two OAuth secret fields, session-repository
tokens, and active task identity credentials.

### Cryptographic invariant

After structural validation, decrypt every non-empty `enc:v1:` value with the
configured key. Traffic must not resume if any row fails authentication,
decoding, or UTF-8 validation.

### Required tests

- Python cipher: G1, G2, G3, empty, unknown version, corrupt payload.
- Python service: non-string stored values fail without string coercion.
- Identity capture: uses the shared Python cipher.
- Migration: mixed G1/G2/G3 across every in-scope store.
- Migration: wrong key, corrupt ciphertext, unknown envelope, and non-string
  values roll back the complete revision.
- Migration: helper idempotency.
- Cross-language vectors: G2 and G3 interoperability.
- Rust: plaintext fails closed, G2/G3 decrypt, empty skips, and identity decoding
  has no separate prefix rule.

## Rollout Gate

Per environment:

1. Confirm a restorable database backup.
2. Freeze credential writes and stop all old HA writers.
3. Run the new migration from an image containing Part A+B.
4. Confirm the Alembic revision is the expected new head.
5. Run structural checks across every in-scope store.
6. Run full cryptographic validation across every non-empty ciphertext.
7. Start API and orchestrator with the same vault key.
8. Observe credential list/read and representative runner injections.
9. Activate Part C.

Any failed gate stops the deployment and leaves traffic disabled until the
problem is corrected or the pre-migration backup is restored.

## Process Guardrails

- A PR changing an envelope prefix or payload format must include reader
  compatibility, a data migration, and cross-language vectors in the same
  change set.
- Readers retain the immediately previous envelope for at least one release and
  until all environments pass the structural and cryptographic invariants.
- No caller may inspect envelope prefixes outside the shared implementation.
- Deployment documentation must name the expected Alembic head and include the
  write-freeze, structural-check, and cryptographic-check steps.

## Operational Follow-up

Production inspection confirmed sensitive API-key/token values stored in
plaintext. After normalization succeeds, rotate those credentials and remove
diagnostic output or logs that exposed value prefixes. Rotation is operationally
required but is separate from the database-format migration.

## Out of Scope

- Redesigning credential-domain names or UI.
- Changing the AES-256-GCM payload format.
- Editing or downgrading the already-applied
  `20260814_000001_unify_credentials` revision.
