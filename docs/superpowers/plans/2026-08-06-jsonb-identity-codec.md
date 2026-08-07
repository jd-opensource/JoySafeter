# JSONB Payload Identity Codec — Initiative Charter

**Date:** 2026-08-06
**Status:** Superseded historical charter — non-executable
**Superseded by:** `../specs/2026-08-07-strict-entity-id-boundaries-design.md`
**Owner:** TBD
**Relation:** Follow-on to the typed-EntityId migration (`2026-08-06-typed-entity-ids-completion-audit.md`). This covers the ONE surface the value-object + `EntityIdType` work does NOT reach: entity identities embedded as **strings inside schemaless JSONB** (`joysafeter_session_events.payload`) and analogous ad-hoc JSON.

> The tolerant-read, dual-match, and optional-backfill instructions below are retained only as
> historical context. They must not be executed. Persisted JSON/JSONB entity references now use one
> canonical prefixed form, with no bare-value compatibility read or query.

## Problem (root cause)

Typed `EntityId` value objects + the `EntityIdType` SQLAlchemy codec make identity **type-safe and format-symmetric at typed columns**. They do NOT reach identities serialized into **schemaless JSONB payloads**. There, an id is just a JSON string whose format (`task_<uuid>` prefixed vs bare `<uuid>`) is decided ad hoc at each call site and matched by exact string equality at each reader. Nothing enforces a single convention; drift is **silent** (a mismatched query returns no rows / False — never an error).

### Current state (verified 2026-08-06, NOT an active bug)
- **`session_events.payload` id values are uniformly PREFIXED today.** Writers: Python `send_event(..., {"task_id": str(task.id)})` (task_submission_service.py:211,216) and Rust `"task_id": task_id.to_string()` / `task.id.to_string()` (scheduler.rs 423/516/1000/1148, sandbox_controller.rs 1301/1331/3290, grpc/server.rs 865/1390/3085/3202/4404). Pass-through: events/persist.rs:80, events/session_state.rs:203/207. Readers: session_service.py `find_status_running_event_for_task` / `task_has_agent_output` match `payload->>'task_id' = str(task_id)` (prefixed). Consistent end-to-end.
- **Physical boundaries are uniformly BARE and correct:** Redis queue/channel (kernel/queue.rs 71/77/114 — the global task queue the Python enqueue.py:24 `str(task_id.uuid)` also feeds), Redis SET (redis_coordinator.rs:178), container fs paths / labels (envoy.rs:216, sandbox_resolver.rs), Redis stream field (stream_publisher.rs:74 `session_id`), gRPC proto to harness (harness_input_builder.rs:230). All `as_uuid().to_string()`.

### Why charter it anyway (the two real gaps)
1. **Convention is unenforced.** The distinction "JSONB payload → prefixed" vs "physical wire/Redis/fs → bare" lives only in developers' heads. A future writer that does `payload["task_id"] = id.as_uuid().to_string()` (bare) — or a reader that matches bare — compiles, passes type checks, passes tests written with the same mistake, and silently breaks the paired query. There is no guard.
2. **Migration-boundary legacy rows.** Both Python (`task.id`) and Rust (`task_id`) flipped bare→prefixed when their respective typed-id migrations landed. Event rows written *before* the migration hold a **bare** `payload.task_id`; the post-migration prefixed-needle readers silently miss them. Benign on greenfield v2 (single initial migration, disposable data) but real if any pre-migration `session_events` data survives a deploy.

## Historical Decision (Superseded)

**Identities embedded in JSONB event payloads use the canonical PUBLIC prefixed form** (`task_<uuid>`, `sess_<uuid>`, `agent_<uuid>`). Rationale: payloads flow to clients over SSE and into logs, so they belong to the *public* boundary, same as API responses; and this matches what every current writer already does (zero migration of the write path). Physical boundaries (Redis keys/queues, container paths, protobuf wire) stay BARE and are out of scope.

**Historical/non-executable:** Reads were proposed to be tolerant of prefixed or bare values. The
strict-boundary design rejects this approach; readers and queries now use only the canonical prefixed
form.

## Scope / Deliverables

- [ ] **HISTORICAL — DO NOT EXECUTE: tolerant Python reads.** The proposed `payload_id_match` /
  `payload_id_read` dual-format behavior is superseded; use only canonical prefixed JSONB values.
- [ ] **Rust codec helper** — a single `payload_id(id) -> String` (= `id.to_string()`, prefixed) used by every `"task_id"/"session_id"/"agent_id"` JSON insertion, so the choice is centralized, not per-call-site. Audit scheduler.rs / sandbox_controller.rs / grpc/server.rs / events/* to route through it.
- [ ] **Guard tests (both languages)** analogous to `test_typed_id_architecture.py`: flag `as_uuid().to_string()` (or bare-uuid) feeding a known payload-id JSON key, and flag payload-id readers using raw exact-match on `payload->>'..._id'` without the tolerant helper. Whitelist the physical-boundary sites explicitly.
- [ ] **Inventory confirmation** of every JSONB payload id key beyond `task_id` (e.g. any `session_id`/`agent_id`/`sandbox_id` in payloads) and every reader, so the rule is applied uniformly (this charter enumerated the `task_id` writers; a full sweep is task #1 of execution).
- [ ] **HISTORICAL — DO NOT EXECUTE: optional JSONB backfill.** No Alembic migration or compatibility
  read path is permitted for this pre-release reset; rebuild data in canonical form.

## Non-goals
- Physical-boundary formats (Redis, fs, protobuf) — those are correctly bare and stay bare.
- The bg-task-tool id in `agent.bg_*` payloads (events/mapping.rs:136) — that is the claude-code harness Task-tool id, a DIFFERENT namespace, not a JoySafeter `TaskId`. Out of scope.

## Completion gates
- [ ] One helper per language is the ONLY way identities enter/leave JSONB payloads; guard tests enforce it and fail on the anti-pattern.
- [ ] **HISTORICAL — DO NOT EXECUTE:** dual prefixed/legacy-bare reader tests are superseded by
  canonical-prefixed-only persistence and query tests.
- [ ] `uv run pytest`, `cargo test`, ruff/fmt green.
