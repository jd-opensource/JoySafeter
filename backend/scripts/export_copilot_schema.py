"""
Export Copilot stream events and GraphAction to a shared JSON Schema file.

Run from repo root:
  python backend/scripts/export_copilot_schema.py
Or from backend directory:
  python scripts/export_copilot_schema.py

Output: docs/schemas/copilot-contract.json
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
action_types_path = backend_dir / "app" / "core" / "copilot" / "action_types.py"
spec = importlib.util.spec_from_file_location("action_types", action_types_path)
assert spec and spec.loader
action_types = importlib.util.module_from_spec(spec)
spec.loader.exec_module(action_types)

GraphAction = action_types.GraphAction
GraphActionType = action_types.GraphActionType
CopilotStatusEvent = action_types.CopilotStatusEvent
CopilotContentEvent = action_types.CopilotContentEvent
CopilotThoughtStepEvent = action_types.CopilotThoughtStepEvent
CopilotToolCallEvent = action_types.CopilotToolCallEvent
CopilotToolResultEvent = action_types.CopilotToolResultEvent
CopilotResultEvent = action_types.CopilotResultEvent
CopilotDoneEvent = action_types.CopilotDoneEvent
CopilotErrorEvent = action_types.CopilotErrorEvent


def main() -> None:
    repo_root = backend_dir.parent
    out_path = repo_root / "docs" / "schemas" / "copilot-contract.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Build combined schema with $defs for all types
    graph_action_schema = GraphAction.model_json_schema()

    # Collect $defs from each stream event model
    defs: dict = {}
    one_of = []

    for model in (
        CopilotStatusEvent,
        CopilotContentEvent,
        CopilotThoughtStepEvent,
        CopilotToolCallEvent,
        CopilotToolResultEvent,
        CopilotResultEvent,
        CopilotDoneEvent,
        CopilotErrorEvent,
    ):
        schema = model.model_json_schema()
        ref = f"#/$defs/{model.__name__}"
        defs[model.__name__] = schema
        one_of.append({"$ref": ref})

    # Merge nested $defs from GraphAction (e.g. GraphActionType enum)
    defs["GraphAction"] = graph_action_schema
    if "$defs" in graph_action_schema:
        for k, v in graph_action_schema["$defs"].items():
            defs[k] = v
    # GraphActionType enum (for reference; Pydantic Enum has no model_json_schema)
    defs["GraphActionType"] = {
        "type": "string",
        "enum": [e.value for e in GraphActionType],
        "description": "Graph action type",
    }

    contract = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CopilotStreamEvent",
        "description": "Copilot WebSocket/SSE stream event contract. One of status, content, thought_step, tool_call, tool_result, result, done, error.",
        "oneOf": one_of,
        "$defs": defs,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(contract, f, indent=2, ensure_ascii=False)

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
