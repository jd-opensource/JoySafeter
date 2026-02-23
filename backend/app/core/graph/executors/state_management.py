"""
State Management Executors - Explicit Data Flow Nodes.
"""

from typing import Any, Dict

from loguru import logger

from app.core.graph.graph_state import GraphState


class GetStateNodeExecutor:
    """Reads specified variables from the global GraphState into the local payload."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.keys_to_fetch = config.get("keys_to_fetch", [])
        self.error_on_missing = config.get("error_on_missing", False)

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute the Get State node.

        Extracts requested keys from global state and returns them as a new dict (payload).
        Returns:
            A dictionary containing the requested variables. This becomes the payload
            for downstream nodes.
        """
        payload: Dict[str, Any] = {}
        missing_keys = []

        # Assuming state is accessible via dict-like interface (or we check context/messages)
        # We check the top level GraphState keys, and also inside context.
        context = dict(state.get("context", {}))

        for key in self.keys_to_fetch:
            if key in state:
                from typing import cast

                payload[key] = cast(dict, state)[key]
            elif key in context:
                payload[key] = context[key]
            else:
                missing_keys.append(key)

        if self.error_on_missing and missing_keys:
            error_msg = f"Failed to fetch requested state variables: {', '.join(missing_keys)}"
            logger.error(f"[GetStateNodeExecutor] {error_msg}")
            # The NodeExecutionWrapper will catch this and handle it via the global error branch
            raise ValueError(error_msg)

        logger.debug(f"[GetStateNodeExecutor] Fetched {len(self.keys_to_fetch)} keys: {self.keys_to_fetch}")

        # We wrap it in a result payload so it doesn't just blind-merge back into state
        # Instead of just returning the payload directly (which merges into global state due to TypedDict spread),
        # we return it under a specific key, like 'node_output'.
        # However, for true explicitly mapped data-flow, we actually DO want it in the payload,
        # but the LangGraph update mechanism merges returned dicts into the typed dict.
        # So we update a 'payload' dict explicitly within the 'node_contexts' or similar scoped state.

        # For now, let's inject it into context to keep it accessible without redefining GraphState right this second
        # But conceptually, this should emit to the next nodes.
        return {"context": payload}


class SetStateNodeExecutor:
    """Writes mapped payload variables to the global GraphState."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.input_mapping = config.get("input_mapping", {})

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute the Set State node.

        Reads from the localized payload mappings and writes to the global state.
        """
        updates: Dict[str, Any] = {}

        # Here we would normally evaluate the input_mapping against the incoming payload.
        # Since we are building the framework, we simulate mapping from the state.context for now.
        context = state.get("context", {})

        for global_key, source_expression in self.input_mapping.items():
            # In a full implementation, source_expression would be evaluated against the payload.
            # E.g. "Node_A.output.user_id"
            # For this MVP step, we just look up the key directly if it exists.
            if source_expression in context:
                updates[global_key] = context[source_expression]
            else:
                logger.warning(f"[SetStateNodeExecutor] Could not resolve mapped source: {source_expression}")

        logger.debug(f"[SetStateNodeExecutor] Updating global state with keys: {list(updates.keys())}")

        # Return dict that LangGraph will merge into the GraphState
        return {"context": updates}
