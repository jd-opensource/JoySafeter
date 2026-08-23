# Credential Internal Naming and Layout Normalization Design

**Date:** 2026-08-21
**Status:** Approved direction — execute after runtime freshness

## Goal

Make internal frontend and backend names match the canonical credential domain without breaking public URLs, stored documents, deployment concepts, or downstream imports in one unsafe step.

## Classification

Legacy names fall into three distinct classes:

1. **Compatibility surfaces to retain:** `/managed/secrets`, `/managed/vaults`, `create=vault`, and persisted v1 reference aliases.
2. **Internal credential names to migrate:** route-owned create dialogs, `mcp-vault-*` components, secret/vault response parsers, compatible-secret hooks, and credential-facing i18n namespaces.
3. **Correct non-credential terminology to retain:** Kubernetes Secret manifests/scripts and any runtime secret/vault abstraction whose semantics are not the unified credential resource.

## Frontend Layout

Move reusable credential components out of redirect-only route directories:

- `app/managed/secrets/components/create-secret-dialog.tsx` → `components/managed/credentials/create-standalone-credential-dialog.tsx`
- `app/managed/vaults/components/create-vault-dialog.tsx` → `components/managed/credentials/create-credential-group-dialog.tsx`
- `app/managed/vaults/components/create-credential-dialog.tsx` → `components/managed/credentials/create-mcp-member-dialog.tsx`
- `mcp-vault-list.tsx` → `mcp-credential-group-list.tsx`
- `mcp-vault-detail.tsx` → `mcp-credential-group-detail.tsx`

Tests move with their implementation. Redirect-only route files remain small and contain no reusable components.

Rename internal symbols toward `Credential`, `ServiceCredential`, `CredentialGroup`, and `McpMember`. Keep temporary re-export shims only where a migration cannot be atomic.

## Backend Layout

Do not split the 1600-line SQLAlchemy repository in the same patch as runtime freshness. The backend normalization proceeds in independent phases:

- move composition roots out of `joysafeter_application` into an outer bootstrap package;
- keep credential management facades in `joysafeter_application/credentials/management_service.py`, never in `joysafeter_domain/services`;
- split resource persistence, group persistence, reference queries, and row mapping into focused infrastructure modules;
- keep application ports free of SQLAlchemy and Pydantic request types.

The management facade has one canonical behavior. Credential mutations always write their audit row in the same transaction. Transaction ownership is controlled only by `auto_commit`: an owning service commits or rolls back, while a non-owning service leaves rollback to its outer transaction. The removed `compatibility_mode` switch was an internal migration artifact that incorrectly coupled audit suppression to rollback behavior; it was never a public compatibility contract.

## Compatibility Rules

- Redirect routes remain indefinitely unless telemetry proves they are unused.
- Public API paths remain `/credentials` and `/credential-groups`.
- Historical docs and migrations are not renamed.
- Kubernetes Secret terminology is not a credential-domain naming defect.
- Persisted v1 aliases remain readable; new writes continue using canonical fields.

## Validation

- Import-boundary tests reject shared components importing route-owned modules.
- Terminology tests distinguish user-facing compatibility strings from internal identifiers.
- Redirect tests preserve old URLs and query aliases.
- Full frontend tests and production build run after file moves.
