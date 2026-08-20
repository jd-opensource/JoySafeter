# Credential Dependency Registry

`CREDENTIAL_DEPENDENCY_REGISTRY_MODE=enforce` is the production default.

- `enforce`: only the descriptor Registry decides Credential and Credential Group archive/delete blockers. Scanner failures fail closed.
- `shadow`: rollback/observation mode. The legacy scanner remains authoritative while the Registry runs for metadata-only semantic comparison.

## Rollback

Set `CREDENTIAL_DEPENDENCY_REGISTRY_MODE=shadow` and restart Backend/Worker processes. Shadow mode does not change persisted data and does not disable lifecycle blockers.

## Verification

Before returning to `enforce`, run the Registry integration, lifecycle concurrency, Snapshot linearization, and reverse-census suites. Inspect `credential_dependency_registry_shadow_diff` records; they contain IDs/counts/dispositions only and never material or raw JSON.
