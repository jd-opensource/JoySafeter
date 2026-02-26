"""
Mapping Utilities - Shared utilities for universal state mapping.

Provides centralized functions to map inputs from the global graph state into
local execution scope, and map output results from the execution scope back
to the global graph state.
"""

from typing import Any, Dict

from loguru import logger


def apply_node_input_mapping(config: Dict[str, Any], state: Any, node_id: str = "unknown") -> Dict[str, Any]:
    """Apply input mapping configuration to extract variables from state.

    Reads from config.input_mapping, searches for the value in state,
    and returns a dictionary of the mapped inputs.
    """
    input_mapping = config.get("input_mapping", [])
    if not input_mapping:
        return {}

    logger.debug(f"[MappingUtils] Applying input mapping for node '{node_id}': {input_mapping}")

    mapped_inputs = {}

    # Helper to safely get value from nested dicts
    def get_value(obj: Any, path: str) -> Any:
        parts = path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return None
            if current is None:
                return None
        return current

    for mapping in input_mapping:
        if isinstance(mapping, dict):
            # Format: {"key": "local_var", "type": "variable", "value": "state.path"}
            param_name = mapping.get("key")
            source_type = mapping.get("type", "static")
            source_value = mapping.get("value")

            if not param_name:
                continue

            if source_type == "variable" and source_value:
                mapped_inputs[param_name] = get_value(state, source_value)
            else:
                mapped_inputs[param_name] = source_value

    return mapped_inputs


def apply_node_output_mapping(
    config: Dict[str, Any], result: Any, return_dict: Dict[str, Any], node_id: str = "unknown"
) -> None:
    """Apply output mapping configuration to update state.

    Extracts values from result based on config.output_mapping and adds them to return_dict.
    """
    output_mapping = config.get("output_mapping", {})

    # NEW DATA-FLOW ARCHITECTURE (Option B):
    # Always save the full raw result payload to 'node_outputs' keyed by node_id.
    # This allows downstream nodes to explicitly wire/map from this payload.
    # It ensures data is localized and not blindly merged into global state.
    if "node_outputs" not in return_dict:
        return_dict["node_outputs"] = {}

    # Convert result to dict if it isn't already, for easier nested mapping
    raw_payload = (
        result.dict() if hasattr(result, "dict") else (result if isinstance(result, dict) else {"value": result})
    )
    return_dict["node_outputs"] = {node_id: raw_payload}

    if not output_mapping:
        return

    logger.debug(f"[MappingUtils] Applying output mapping for node '{node_id}': {output_mapping}")

    # Helper to safely get value from nested dicts
    def get_value(obj: Any, path: str) -> Any:
        if path == "result":
            return obj

        parts = path.split(".")
        current = obj

        # If path starts with "result.", skip the first part
        if len(parts) > 0 and parts[0] == "result":
            parts = parts[1:]

        for part in parts:
            # Support list index via numeric keys
            if isinstance(current, list) and part.isdigit():
                try:
                    idx = int(part)
                    if 0 <= idx < len(current):
                        current = current[idx]
                        continue
                    else:
                        return None
                except (ValueError, IndexError):
                    return None

            if isinstance(current, dict):
                current = current.get(part)
            elif hasattr(current, part):
                current = getattr(current, part)
            else:
                return None

            if current is None:
                return None
        return current

    output_items = {}
    if isinstance(output_mapping, dict):
        output_items = output_mapping
    elif isinstance(output_mapping, list):
        for item in output_mapping:
            if isinstance(item, dict) and "key" in item and "value" in item:
                output_items[item["key"]] = item["value"]

    for state_key, result_path in output_items.items():
        try:
            # Extract value
            value = get_value(result, result_path)

            if value is not None:
                return_dict[state_key] = value
                logger.debug(f"[MappingUtils] Mapped {result_path} -> {state_key} = {str(value)[:50]}...")
        except Exception as e:
            logger.warning(
                f"[MappingUtils] Failed to map output {result_path} -> {state_key} for node '{node_id}': {e}"
            )
