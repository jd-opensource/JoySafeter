# Credential Runtime and Lifecycle Closure Design

**Date:** 2026-08-21

## Goal

Close the highest-risk consistency gaps between credential mutations, MCP runtime resolution, credential-group lifecycle, and live sandbox refresh behavior.

## Decisions

1. MCP runtime resolution treats archived and deleted members as absent. An inactive member must not invalidate the remaining active group members.
2. Deleting a credential group soft-deletes every non-deleted member in the same transaction. This prevents visible, name-reserving members whose parent group can no longer be managed.
3. Restoring a credential group validates only active members. Archived members remain archived and may be restored individually after their parent group is active.
4. Network-policy refresh remains limited to egress-backed credential usages. Direct environment injection is not represented as successfully refreshed because an existing container environment cannot be mutated by the current providers.
5. Existing public routes and stored v1 reference documents remain compatible in this phase.

Direct injection changes use the existing `REVALIDATE_ON_ACTIVATION` disposition. They do not set `networking_status=pending` and do not enqueue a `network_policy_refresh` command. Environment update audit details record `runtime_restart_required=true`; the new material is applied when the runtime is next activated or recreated.

## Invariants

- Runtime MCP routes contain active groups and active members only.
- A deleted group has no non-deleted members.
- An archived group may contain archived members and can still be restored.
- An archived MCP member may only be restored when its parent group is active.
- Credential changes must not claim successful runtime propagation for unsupported direct environment injection.
- No plaintext credential value is added to logs, audit metadata, or API responses.

## Deferred Work

- New `disabled`/`revoked` lifecycle states.
- Material versioning, key IDs, keyring-based rewrap, and usage timestamps.
- Full frontend Secret/Vault naming migration.
- Repository and composition-root restructuring.
