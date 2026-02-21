"""
Transform Executors - Executors for data transformation (JSON, Aggregator).
"""

import json
import time
from typing import Any, Dict

from langchain_core.messages import AIMessage
from loguru import logger

from app.core.graph.executors.agent import apply_node_output_mapping
from app.core.graph.graph_state import GraphState
from app.models.graph import GraphNode


class JSONParserNodeExecutor:
    """Executor for JSON Parser node.

    Parses a string (e.g. from LLM) into a JSON object and maps fields to state.
    """

    STATE_READS: tuple = ("messages", "*")
    STATE_WRITES: tuple = "*"

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id

        data = self.node.data or {}
        self.config = data.get("config", {})
        self.source_field = self.config.get("sourceField", "messages[-1].content")

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Parse JSON."""
        # Resolve source value...
        # Needs logic similar to StateWrapper access.
        # For now assuming it grabs last message content if not specified or simple path.

        content = ""
        # Simplified retrieval:
        if self.source_field == "messages[-1].content":
            msgs = state.get("messages", [])
            if msgs:
                content = msgs[-1].content if hasattr(msgs[-1], "content") else str(msgs[-1])
        else:
            # TODO: Use StateWrapper/expression evaluator to fetch arbitrary path
            content = "{}"

        cleaned_content = content.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(cleaned_content)

            return_dict = {"current_node": self.node_id}
            apply_node_output_mapping(self.config, parsed, return_dict, self.node_id)

            return return_dict
        except Exception as e:
            logger.error(f"[JsonParser] Failed to parse JSON: {e}")
            return {"messages": [AIMessage(content=f"JSON Parse Error: {e}")]}


class AggregatorNodeExecutor:
    """Executor for an Aggregator node in the graph (Fan-In).

    Waits for all upstream nodes to complete and aggregates their results.
    Supports error handling strategies: fail_fast or best_effort.
    Also supports generic aggregation methods: append, sum, merge, latest.
    """

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.error_strategy = self._get_error_strategy()

        data = self.node.data or {}
        self.config = data.get("config", {})
        self.method = self.config.get("method")
        self.source_variables = self.config.get("source_variables", [])
        self.target_variable = self.config.get("target_variable")

    def _get_error_strategy(self) -> str:
        """Extract error handling strategy from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        error_strategy = config.get("error_strategy", "fail_fast")  # 'fail_fast' or 'best_effort'
        return str(error_strategy) if error_strategy is not None else "fail_fast"

    def _aggregate_results(self, state: GraphState) -> Dict[str, Any]:
        """Aggregate results from parallel branches (Fan-In logic)."""
        task_results = state.get("task_results", [])
        state.get("parallel_results", [])

        # Check for errors
        errors = [r for r in task_results if r.get("status") == "error"]
        successes = [r for r in task_results if r.get("status") == "success"]

        if self.error_strategy == "fail_fast" and errors:
            # One failure causes all to fail
            error_msg = f"Aggregation failed: {len(errors)} error(s) found"
            logger.error(
                f"[AggregatorNodeExecutor] Fail-fast triggered | node_id={self.node_id} | errors={len(errors)}"
            )
            return {
                "status": "error",
                "error_msg": error_msg,
                "errors": errors,
            }

        # Best-effort: collect successes, mark failures
        aggregated = {
            "status": "success",
            "success_count": len(successes),
            "error_count": len(errors),
            "results": [r.get("result") for r in successes],
            "errors": errors if errors else None,
        }

        return aggregated

    def _perform_generic_aggregation(self, state: GraphState) -> Dict[str, Any]:
        """Perform generic aggregation based on method."""
        if not self.target_variable:
            logger.warning(f"[AggregatorNodeExecutor] No target_variable defined for method={self.method}")
            return {}

        values = []
        for source in self.source_variables:
            val = state.get(source)
            if val is not None:
                if isinstance(val, list):
                    values.extend(val)
                else:
                    values.append(val)

        result_val = None

        if self.method == "append":
            result_val = values
        elif self.method == "sum":
            result_val = sum(v for v in values if isinstance(v, (int, float)))
        elif self.method == "merge":
            result_val = {}
            for v in values:
                if isinstance(v, dict):
                    result_val.update(v)
        elif self.method == "latest":
            result_val = values[-1] if values else None
        else:
            logger.warning(f"[AggregatorNodeExecutor] Unknown aggregation method: {self.method}")
            return {}

        return {self.target_variable: result_val}

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Aggregate results from all upstream nodes."""
        start_time = time.time()

        # If generic aggregation method is specified, use it
        if self.method:
            logger.info(
                f"[AggregatorNodeExecutor] >>> Aggregating generic | "
                f"node_id={self.node_id} | method={self.method} | target={self.target_variable}"
            )
            try:
                result = self._perform_generic_aggregation(state)
                result["current_node"] = self.node_id
                result["status"] = "success"
                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"[AggregatorNodeExecutor] <<< Aggregation complete | "
                    f"node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms"
                )
                return result
            except Exception as e:
                logger.error(f"[AggregatorNodeExecutor] Error in generic aggregation: {e}")
                return {"current_node": self.node_id, "messages": [AIMessage(content=f"Error: {e}")]}

        # Fallback to Fan-In logic
        logger.info(
            f"[AggregatorNodeExecutor] >>> Aggregating Fan-In | node_id={self.node_id} | strategy={self.error_strategy}"
        )

        try:
            aggregated = self._aggregate_results(state)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[AggregatorNodeExecutor] <<< Aggregation complete | "
                f"node_id={self.node_id} | status={aggregated.get('status')} | "
                f"elapsed={elapsed_ms:.2f}ms"
            )

            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=f"Aggregation complete: {aggregated.get('status')}")],
                "aggregated_results": aggregated,
            }
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[AggregatorNodeExecutor] !!! Error aggregating | "
                f"node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms | "
                f"error={type(e).__name__}: {e}"
            )
            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=f"Aggregation error: {str(e)}")],
                "aggregated_results": {
                    "status": "error",
                    "error_msg": str(e),
                },
            }
