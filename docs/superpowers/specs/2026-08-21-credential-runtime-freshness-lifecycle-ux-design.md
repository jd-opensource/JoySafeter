# Credential Runtime Freshness and Lifecycle UX Design

**Date:** 2026-08-21
**Status:** B2 revision 2 — independently approved for implementation

## Goal

Represent credential-bearing runtime drift as durable state, prevent stale or mixed-generation runtime activation, expose effective runtime freshness through a session API, and complete MCP credential-group/member lifecycle controls without conflating runtime configuration with network-policy refresh.

## Core Invariants

1. A session-bound sandbox is effectively current only when its raw runtime status is `ready` and its applied runtime generation equals the session desired runtime generation.
2. A stale resolution may not complete an authoritative `ready` write after a newer credential-bearing mutation commits.
3. Runtime resolution, task attachment, and harness materialization may not silently mix different runtime generations.
4. Active `running`, `creating`, or `provisioning` runtimes are never automatically destroyed because configuration became stale.
5. Session snapshots remain immutable audit records. Only the explicitly defined credential-bearing environment slice is live-bound.
6. Explicit environment bindings fail closed across lifecycle and project boundaries.

## Persisted Freshness Model

The existing sandbox-facing freshness tuple remains:

- `joysafeter_sandboxes.runtime_config_status TEXT NOT NULL DEFAULT 'ready'`
- `joysafeter_sandboxes.runtime_config_last_reason TEXT NULL`
- `joysafeter_sandboxes.runtime_config_required_at TIMESTAMPTZ NULL`

Supported raw status values are `ready` and `restart_required`.

Add desired-generation metadata to sessions and applied generation to sandboxes:

- `joysafeter_sessions.runtime_config_generation BIGINT NOT NULL DEFAULT 0`
- `joysafeter_sessions.runtime_config_generation_reason TEXT NULL`
- `joysafeter_sessions.runtime_config_generation_updated_at TIMESTAMPTZ NULL`
- `joysafeter_sandboxes.runtime_config_applied_generation BIGINT NOT NULL DEFAULT 0`

The session generation identifies the latest credential-bearing runtime configuration desired by the session. The sandbox applied generation identifies the desired generation used at the activation linearization point. The distinct `applied` name is required in Python, Rust, SQL, API-internal joins, tests, and documentation.

## Runtime Environment Authority

The live authority is deliberately narrower than the complete environment object.

### Frozen Snapshot Slice

The activation snapshot remains authoritative for:

- image and package selection;
- setup commands;
- ordinary non-credential environment variables;
- networking mode and ordinary allowed-host configuration;
- base mounts plus immutable session-specific overlays and required storage mounts;
- agent prompt, tools, model selection, version, and other agent fields.

Existing session overlay and mount material must remain session-scoped. Runtime assembly consumes the frozen merged snapshot slice, or an equivalent separately persisted session overlay; a live environment read must never discard the overlay or leak it to another session.

`environment_config_overlay` is a legacy internal frozen-slice seam, not a second credential-binding authority. It accepts only an explicit allowlist of frozen configuration keys and must reject any overlay that contains or decodes to `environment_credential_ids`, `secret_refs`, legacy `service_credential_id`, `egress_services`, or future credential-bearing fields. Session storage mounts continue through the separately typed `environment_mount_resources` path. Current production callers do not supply the generic overlay; retaining it requires validation tests rather than implicit trust.

### Live Credential-Bearing Slice

The canonical active environment binding is authoritative only for:

- direct credential references and their injection targets;
- HTTP/MCP egress service definitions and their credential references.

Credential values are always late-bound by credential public ID from the active credential store. Updating frozen-slice fields affects newly activated sessions but does not retroactively change an existing session runtime generation.

The sandbox resolver, credential impact targeting, harness input builder, and network-policy recovery path must use the same split-authority rule.

## Canonical Environment Binding

- Every new session creation path resolves an environment name or ID under the session project and persists the canonical environment public ID in `session.environment_ref`.
- This applies to the Python Session API, task auto-session creation, trigger/session creation paths, and the Rust scheduler snapshot path.
- The locked environment re-read supplies the canonical ID; the original input may remain only in immutable audit material.
- If `session.environment_ref` is present, missing, deleted, archived, or cross-project resolution is a terminal fail-closed error. Snapshot fallback is forbidden.
- A pre-migration non-empty `session.environment_ref` that is not a public ID may be resolved as a legacy name only when it resolves uniquely inside the exact project; failure is terminal, and successful resolution uses the canonical ID for runtime decisions and may canonicalize the stored binding under the session lock.
- Legacy snapshot fallback is allowed only when `session.environment_ref` is genuinely absent. Legacy lookup prefers snapshot environment ID; snapshot name matching is compatibility-only and must resolve uniquely inside the exact project.
- Project comparison is exact and null-safe. A project-scoped session cannot bind a global or different-project environment, and an explicitly global session cannot bind a project environment.

## Mutation Disposition Matrix

One logical mutation computes both runtime and network dispositions before persistence:

| Change | Runtime generation | Sandbox raw status | Network policy |
| --- | --- | --- | --- |
| Direct environment credential binding added, removed, or retargeted | Advance once per affected session | Mark matching live sandbox `restart_required` | No refresh unless the same mutation also affects egress |
| Value/version change or restore of a directly referenced credential | Advance once per affected session | Mark matching live sandbox `restart_required` | No refresh unless also referenced by egress |
| HTTP/MCP egress service definition or egress-only credential change | Unchanged | Unchanged | Existing hot refresh path |
| Mixed direct and egress impact | Advance once per affected session | Mark matching live sandbox `restart_required` | Also execute hot refresh |
| Frozen snapshot slice change | Unchanged for existing sessions | Unchanged | Existing behavior; applies to future session snapshots |
| Semantic no-op | Unchanged | Unchanged | No refresh |

The resource mutation, audit row, generation advance, sandbox stale mark, and network disposition enqueue execute in one database transaction. Rollback removes all of them.

Credential metadata/name-only updates, empty patches, and material updates whose semantic plaintext value is unchanged do not emit runtime or network impacts. Credential restore recomputes current live usage and emits direct, egress, or mixed impact as applicable. Credential archive/delete remains governed by the P0 dependency blocker: if an active live or snapshot dependency exists, the mutation fails before state change and performs no generation/network write; a successful archive/delete therefore has no affected active session.

Environment creation emits no runtime or network impact because no valid active session can already be canonically bound to the new environment. Environment archive/delete retains the existing active task/agent/trigger/session blockers and performs no generation write on failure or on a successful unreferenced lifecycle change. Environment restore does not exist and is outside this plan.

Egress-only invalidation retains the existing project-scoped conservative network refresh in this phase. Exact per-environment egress targeting is a later optimization; it must never cause a runtime generation bump. Direct targeting must be exact to canonical live environment bindings, with snapshot decoding only for sessions whose binding is absent.

## Mutation Linearization

Affected active session rows are locked in deterministic database-ID order. The mandatory lock order is:

```text
session -> sandbox
```

For each affected session, the mutation transaction:

1. locks the active session row with `FOR UPDATE`;
2. advances `runtime_config_generation` exactly once for the logical mutation;
3. writes the latest generation reason and timestamp;
4. locks and marks matching non-destroyed live sandboxes `restart_required` without changing networking state;
5. preserves any newer or more specific sandbox stale marker according to the existing no-clobber rules.

Sessions without a sandbox still advance. Unattached pool rows never advance and are not marked stale.

## Guarded Ready Writers

Every session-bound `ready` writer in Rust and Python uses the same session-row serialization. A plain generation comparison under PostgreSQL `READ COMMITTED` is not a compare-and-swap and is insufficient.

The authoritative new, stopped, and pool paths must:

1. lock the session row first;
2. validate active lifecycle, exact/null-safe project scope, and captured generation;
3. lock the existing sandbox row when one exists;
4. write `ready`, clear raw reason/time, and set `runtime_config_applied_generation` to the captured generation in the same transaction;
5. return a typed zero-write outcome when validation fails.

New sandbox insertion holds the session lock through the insert. Stopped claims preserve the previous raw freshness tuple and previous applied generation. Their claim token and compensation predicate include the applied-generation sentinel, so provider failure restores the exact tuple only if no newer mutation or claim has changed the row.

Pool reservation remains freshness-neutral while unattached. Guarded pool activation atomically locks the session then pool sandbox and writes session attachment, project, fingerprint, ready tuple, applied generation, and timestamps. There is no attached-but-unguarded ready window.

Python `create_sandbox`, stopped activation, and pool attachment remain supported parity boundaries and must use the same generation guard; generic state-machine transitions remain freshness-neutral.

## Resolution, Dispatch, and Harness Fence

`build_resolve_context` captures:

- the canonical environment binding;
- the frozen snapshot slice and session overlay;
- the live credential-bearing slice and late-bound credential material;
- the session desired runtime generation.

The lifecycle is fenced at three boundaries:

1. **Ready write:** session-row-locked new/stopped/pool activation records the captured generation.
2. **Task attach:** the scheduler atomically requires raw `ready`, sandbox applied generation equal to session desired generation, valid session lifecycle/project scope, and the expected sandbox ownership.
3. **Harness materialization:** the builder performs a generation seqlock: read desired generation and sandbox applied generation/status, materialize all live credential-bearing data, then reread. It succeeds only when both reads match, the generation equals the sandbox applied generation, and raw status remains `ready`.

If a mutation commits after the final harness check, the activation may proceed with the already materialized old generation; the mutation then marks the runtime stale for subsequent dispatch. A builder may never combine old runtime state with newly read credential-bearing material.

## Typed Outcomes and Retry Policy

- `GenerationChanged`: transient zero-write outcome; discard the context and retry resolution within a strict bound, then defer to scheduler backoff.
- `RuntimeRestartRequired`: non-reusable active runtime; surface an explicit restart-required task/session outcome and do not call provider destroy.
- `SessionBindingInvalid`: missing, terminated, archived, cross-project, or explicitly bound environment invalid; terminal fail-closed outcome.
- `Conflict`: unique/ownership conflict; reread authoritative state before deciding retry.
- `CleanupFailed`: provider or attached-row cleanup did not complete; stop immediate retries and do not create a second provider runtime.

For a new provider resource rejected by the DB generation guard, successful provider teardown is required before retry. If teardown fails, return `CleanupFailed`.

For a pool sandbox already atomically attached when later provider status, start, file injection, or network setup fails, conditional compensation uses the attachment/claim token under `session -> sandbox` locks. A successfully destroyed provider may transition to the existing terminal/destroyed cleanup state. If provider cleanup fails, the row remains attached and non-ready for reconciliation; it is never silently returned to the pool and no replacement is created in the same attempt.

Idle/stopped runtimes may be replaced or reprovisioned only at the next explicit task activation using a freshly resolved context. For a running session, the user-visible recovery path is `Stop Session` followed by the next task activation; Task 3C must prove that this path replaces/reprovisions the stale runtime rather than silently reusing it. This phase does not add automatic recreation.

## Migration and Rollout

Migration `20260821_000004` is additive and linear after `20260821_000003`.

- Sessions satisfying `archived_at IS NULL AND status <> 'terminated'` are backfilled to desired generation `1`, with migration reason and migration timestamp. This includes idle, running, and rescheduling sessions.
- Attached, non-destroyed sandboxes are backfilled with applied generation `0`. Existing raw `restart_required` reason/time is preserved. A raw-ready attached sandbox therefore becomes effectively stale through generation mismatch.
- Unattached pool sandboxes remain raw `ready` with applied generation `0`.
- Inactive/terminated sessions may remain generation `0` because they cannot be activated without lifecycle validation.
- Downgrade removes sandbox applied generation and session generation metadata before returning to revision `000003`.

Mixed old/new runtime writers are unsupported. Deployment is migration-first and coordinated as one version: quiesce session activation plus credential/environment writes, apply the additive migration, deploy all Python and Rust readers/writers containing Tasks 3A–3C, then resume traffic. Generation-bumping writers and live credential authority must not run while an old unguarded resolver, task attach path, or harness builder is serving.

## Effective Runtime Status API

Add `GET /sessions/{session_id}/runtime-status`. The response is always an object for an accessible session, including when no sandbox exists:

```text
session_id
sandbox_id | null
sandbox_status | null
runtime_config_status | null
runtime_config_last_reason | null
runtime_config_required_at | null
networking_status | null
networking_policy_version | null
networking_policy_hash | null
networking_last_error | null
networking_ready_at | null
```

`runtime_config_status` is effective, not the raw database value:

1. no non-destroyed sandbox: runtime fields are `null`;
2. raw `restart_required`: return `restart_required` with sandbox reason/time;
3. raw `ready` but applied generation differs from desired: return `restart_required` with session generation reason/time;
4. raw `ready` and generations equal: return `ready` with null reason/time.

Destroyed sandboxes are treated as no sandbox. Stopped attached sandboxes use the same truth table. Project-scoped and super-user access reuse existing session authorization. Existing `/network-policies/sessions/{session_id}` behavior and response shape remain unchanged.

## Frontend Behavior

- Show a warning banner when effective `runtime_config_status` is `restart_required`.
- Explain that new credential values apply only after the runtime is explicitly recreated.
- Do not claim refresh success and do not label runtime drift as a network failure.
- Keep network-policy hash/version/error/readiness in a separate status group.
- No-sandbox state is rendered as not provisioned rather than an error.

## MCP Lifecycle UX

- Archived credential groups expose `Restore` and `Delete` actions in list and detail views.
- Archived group members expose `Restore` and `Delete` actions when the parent group is active.
- While the parent group is archived, member mutation actions remain disabled with an explanation.
- Group restore leaves archived members archived, matching the backend lifecycle contract.
- All actions retain project read-only and stale-scope guards.

## Compatibility

- Preserve `/managed/secrets` and `/managed/vaults` as redirect-only routes.
- Preserve existing credential and credential-group API routes and v1 identifier formats.
- Preserve P0 active snapshot lifecycle blockers, credential lock linearization, and exact project isolation.
- Do not reinterpret `networking_status` as runtime freshness.
- Mark contradictory pre-R1 Task 3 report passages as historical evidence during final documentation cleanup.

## Validation

- Alembic tests cover upgrade from `000003`, conservative backfill, defaults, nullability, preserved stale reasons, and downgrade.
- Double-connection PostgreSQL barrier tests prove both serialization orders for new, stopped, and pool activation without sleeps.
- Mutation tests cover direct-only, egress-only, mixed, no-op, rollback, one-bump-per-session, and sessions without sandboxes.
- Canonical binding tests cover all Python and Rust session creation paths, name/ID equivalence, and explicit binding fail-closed behavior.
- Overlay tests prove session mounts survive, live credential bindings update, and overlays do not leak across sessions.
- Overlay validation tests prove credential-bearing direct, egress, legacy alias, and mixed keys are rejected while allowlisted frozen-only overlays remain snapshot-scoped.
- Dispatch and harness tests cover mutations before attach, during material reads, and after the final generation check.
- Failure-path tests cover exact stopped compensation, pool attached cleanup, cleanup failure, bounded retries, typed restart-required handling, and no provider auto-destroy.
- API tests cover the complete effective-status truth table, stopped/destroyed/no-sandbox cases, project isolation, super-user access, and full network summary compatibility.
- Frontend tests cover the runtime warning, no-sandbox state, and complete MCP lifecycle actions.
