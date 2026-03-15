# Schemas

## copilot-contract.json

Canonical JSON Schema for Copilot WebSocket/SSE stream events and GraphAction.

- **Source of truth**: `backend/app/core/copilot/action_types.py` (Pydantic models).
- **Regenerate**: From repo root run:
  ```bash
  python backend/scripts/export_copilot_schema.py
  ```
- **Consumers**: Frontend types in `frontend/types/copilot.ts` and `frontend/hooks/use-copilot-websocket.ts` are kept in sync with this schema; when adding or changing event/action fields, update the backend models, re-run the script, then update the frontend types.

## copilot-apply-fixtures.json

Shared test cases for the apply-actions contract: given `(initial_nodes, initial_edges, actions)`, both backend and frontend must produce the same `(expected_nodes, expected_edges)` (contract match: id/type/position/data.label/data.type/config superset for nodes; id/source/target for edges).

- **Backend test**: `backend/tests/core/copilot/test_action_applier.py`
- **Frontend test**: `frontend/utils/copilot/__tests__/actionProcessor.contract.test.ts`
- When changing apply logic (e.g. new action type or edge case), add or update a case in this file and run both tests.

## Node type default config (contract)

- **Source of truth for defaults**: Frontend `frontend/app/workspace/[workspaceId]/[agentId]/services/nodeRegistry.tsx` (defaultConfig and label per type).
- **Backend**: `backend/app/core/copilot/action_applier.py` keeps `NODE_DEFAULT_CONFIGS` and `NODE_LABELS` in sync with nodeRegistry when adding or changing node types; no separate JSON is used.

## Type and naming conventions

- **Domain / API contract types**: `frontend/types/copilot.ts` — GraphAction, CopilotResponse, stream event shapes; aligned with backend and `docs/schemas/copilot-contract.json`.
- **UI-only types**: `frontend/lib/copilot/types.ts` — e.g. ToolCallState, ToolCallGroup for tool-call display; not part of the API contract. Use these for presentation state only.
