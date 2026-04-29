# Follow-up: Frontend WebSocket Observation Protocol Migration

**Created:** 2026-04-29
**Status:** Open — backend OTel refactor merged; frontend must be updated before the new pipeline lands in a release.
**References:**
- Backend spec: `docs/superpowers/specs/2026-04-29-observation-callback-handler-refactor-design.md` §4.1, §4.3
- Frontend viewer spec: `docs/superpowers/specs/2026-04-28-frontend-observation-viewer-design.md`

## Context

The backend `ObservationCallbackHandler` was rewritten on top of OpenTelemetry (commits `267ffdb7`..`830e7383`). The new `BroadcastProcessor` emits a different WebSocket envelope and event vocabulary than the old `broadcaster.py`. The frontend trace viewer in `frontend/components/observation/` still parses the old shape.

## Required Frontend Changes

### 1. Envelope shape

Old (from `broadcaster.py`):

```json
{ "event": "...", "observation": { ... } }
```

New (from `BroadcastProcessor._emit`):

```json
{
  "event": "span_open" | "span_close" | "span_update" | "llm_token",
  "trace_id": "...",
  "observation_id": "...",
  "parent_observation_id": "..." | null,
  "seq": 1,
  "data": { ... }
}
```

### 2. `ObservationEvent` type

In `frontend/components/observation/`:

- **Delete** `"record"`
- **Add** `"llm_token"`
- **Add** `"span_update"`
- Keep `"span_open"` and `"span_close"` (envelope shifted, but names unchanged)

### 3. New event handlers

- **`llm_token`** — append token to a per-observation stream buffer; flush via `requestAnimationFrame` to avoid render thrash. Payload includes `token` (string) and `index` (int).
- **`span_update`** — patch the existing observation node's attributes. Notably, `on_agent_action` mutates `type: CHAIN` → `type: AGENT` mid-flight. Treat `span_update` as authoritative for any field it carries.

### 4. Parent linkage

`parent_observation_id` is now top-level on the envelope, not nested under `observation`. The renderer should use it to construct the trace tree without inspecting the `data` payload.

## Coordination

Backend and frontend must ship together — the new backend will not produce the old `{"observation": ...}` shape, and the old frontend will not understand the new events. Suggest gating the rollout behind a feature flag if a same-PR landing isn't possible.
