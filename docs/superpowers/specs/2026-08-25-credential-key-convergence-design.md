# Credential Key Convergence Design

## Problem

The local PostgreSQL database contains `enc:v1` credential material written by
two different legacy AES keys. Because v1 envelopes do not carry a key ID, the
currently running services can decrypt only the rows written by their own key.
Older model credentials fail before MCP planning with `envelope_invalid`, and
credential PATCH requests fail with `INTERNAL_ERROR` because the repository
decrypts the old row before applying replacement values.

The affected MCP server is configured with `auth_requirement: none`, the
session has no MCP credential-group bindings, and the runtime never attempted
an MCP credential reveal. MCP authentication is not the failing boundary.

## Invariants

1. Every persisted sensitive value must be decryptable by the configured
   runtime readers.
2. New writes must use a key-ID-bearing `enc:v2:<key_id>:` envelope.
3. API, worker, and orchestrator must use the same keyring and write key ID.
4. A full plaintext credential replacement must not require decrypting the old
   material.
5. A partial update containing masked placeholders must fail with a specific,
   actionable application error when old material cannot be decrypted.
6. MCP servers with `auth_requirement: none` must not select or reveal MCP
   credentials.

## Recovery Design

Stop credential writers, create a PostgreSQL backup, and run a one-off atomic
migration. The migration tries the two recovered legacy keys for each v1 value,
requires exactly one plaintext result, and rewrites every sensitive value with
one active v2 key ID. It also creates and validates the v2 key canary. No
plaintext is logged or written outside the transaction.

After migration, configure every local worktree used for deployment with the
same v2 keyring and write key ID, recreate API/worker/orchestrator, and verify
that storage contains only the active v2 envelope.

## API Repair Design

Credential update data is a complete submitted map whose masked values mean
"preserve the existing plaintext". When the submitted map contains no masked
values, validate and encrypt it directly without revealing the old row. When
masked preservation is requested, retain the current merge behavior; translate
an unreadable old envelope into `CREDENTIAL_MATERIAL_UNREADABLE` with a
`fix_input` action instructing the caller to re-enter all fields.

## Verification

- Regression test: full replacement succeeds when the old row uses another key.
- Regression test: masked partial replacement returns the explicit application
  error instead of an unhandled 500.
- Existing masked-preservation and credential update tests remain green.
- Database inventory reports only the active v2 key ID.
- API, worker, and orchestrator start successfully with canary validation.
- The reported session can run far enough to exercise the unauthenticated MCP
  configuration without any MCP credential access audit.

## Rollback

Keep the pre-migration PostgreSQL custom-format dump. If migration or startup
verification fails, stop writers and restore that dump before making further
changes. The recovered source keys remain available until verification is
complete.
