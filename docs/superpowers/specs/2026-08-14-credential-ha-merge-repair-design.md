# Credential + HA Merge Repair Design

## Objective

Make `joysafeter-v2-0814` a staging-safe integration of the unified credential work and the latest `origin/joysafeter-v2-ha`, with a production-safe forward database migration and all mandatory CI gates passing.

## Integration Strategy

Merge the latest HA branch before repairing shared files. Resolve conflicts by preserving both contracts:

- retain typed entity IDs and ID-based credential references;
- retain the latest HA, K8s, xDS leadership, runner timezone, and deployment behavior;
- retain the unified `/credentials` and `/credential-groups` UI while porting any still-relevant vault lifecycle fixes to that surface;
- do not restore retired `/secrets` or `/vaults` APIs as live implementations.

The merge is performed without committing or pushing.

## Migration Contract

The forward migration from `20260803_000001` must be online-only, transactional, data-preserving, and fail closed before destructive changes.

It must:

1. Rename `joysafeter_agents.mcp_configs` to `mcp_servers` without changing JSON values.
2. Create the unified credential/group schema and migrate legacy rows.
3. Reject every secret or vault with a null `project_id`, including soft-deleted rows, because the destination schema is non-nullable.
4. Reject unresolved live references before dropping legacy columns:
   - agent `secret_ref`;
   - trigger `secret_ref`;
   - environment `secret_refs` and `credential_ref`;
   - session `vault_ids` and snapshot `secret_ref`.
5. Reject a legacy secret that is simultaneously consumed as model and service material. Operators must split or reassign it before migration rather than accepting an ambiguous automatic classification.
6. Preserve the latest live duplicate name as canonical if a dirty legacy database bypassed historical uniqueness constraints.
7. Leave no ORM-to-database drift for application-owned columns and constraints. HA tables intentionally managed outside ORM metadata are documented exceptions.

The migration remains irreversible. Offline SQL generation and downgrade are explicitly unsupported; tests must validate this policy and exercise real PostgreSQL upgrades instead.

## CI Repair Contract

Fix only errors exposed by mandatory repository gates:

- backend Ruff and Mypy;
- backend tests and typed-ID architecture guards;
- frontend tests and production build;
- orchestrator and sandbox-runner rustfmt, Clippy, and tests;
- `git diff --check`.

Warnings that are not promoted to CI errors are not broad refactoring targets unless introduced in the touched merge paths.

## Verification

Verification requires:

- migration regression tests that fail before each production fix;
- upgrade from a real pre-migration PostgreSQL schema containing representative legacy data;
- `alembic check` with only explicitly documented non-ORM HA objects ignored;
- full backend, frontend, orchestrator, and sandbox-runner CI-equivalent commands;
- a final ancestry check proving both source branches and latest HA are ancestors of the worktree HEAD or active merge result.

## Non-Goals

- No push, commit, deployment, or staging database mutation.
- No unrelated warning cleanup or architectural refactor.
- No automatic destructive cleanup of ambiguous legacy credential data.
