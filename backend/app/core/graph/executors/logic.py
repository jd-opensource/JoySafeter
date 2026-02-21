"""
Logic Executors - Executors for control flow nodes (Condition, Router, Loop).
"""

import time
from typing import Any, Dict, List, Optional, Union

from loguru import logger

try:
    from langgraph.types import Command

    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None  # type: ignore[assignment,misc]

from app.core.graph.expression_evaluator import StateWrapper, validate_condition_expression
from app.core.graph.graph_state import GraphState
from app.core.graph.route_types import RouteKey
from app.models.graph import GraphNode


def increment_loop_count(state: GraphState) -> Dict[str, Any]:
    """Manually increment global loop count (legacy helper)."""
    current = state.get("loop_count", 0)
    return {"loop_count": current + 1}


class ConditionNodeExecutor:
    """Executor for a Condition node in the graph.

    Evaluates a condition expression and returns a route decision.
    The returned route_key will be used by LangGraph's conditional edges.
    """

    STATE_READS: tuple = ("*",)  # Expression-dependent — reads any field
    STATE_WRITES: tuple = ("route_decision", "route_history")

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.expression = self._get_expression()

        # Pre-validate expression for safety
        if not validate_condition_expression(self.expression):
            raise ValueError(f"Invalid condition expression in node '{node_id}': {self.expression}")

        # Map handle IDs to route keys (set during graph building)
        self.handle_to_route_map: Dict[str, str] = {}

        # Support trueLabel and falseLabel for better logging/debugging
        data = self.node.data or {}
        config = data.get("config", {})
        self.trueLabel = config.get("trueLabel", "Yes")
        self.falseLabel = config.get("falseLabel", "No")

    def _get_expression(self) -> str:
        """Extract condition expression from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        expression = config.get("expression", "")
        return str(expression) if expression is not None else ""

    def set_handle_to_route_map(self, handle_map: Dict[str, str]) -> None:
        """Set the mapping from React Flow handle IDs to route keys."""
        self.handle_to_route_map = handle_map

    def _evaluate_expression(self, state: GraphState) -> bool:
        """Safely evaluate the condition expression."""
        if not self.expression:
            logger.warning(f"[ConditionNodeExecutor] No expression provided for node '{self.node_id}'")
            return False

        try:
            # Convert state to dict for debugging and wrapping
            state_dict = dict(state)

            # Debug: Print state keys and loop_count value
            logger.debug(
                f"[ConditionNodeExecutor] State keys | "
                f"node_id={self.node_id} | keys={list(state_dict.keys())} | "
                f"loop_count={state_dict.get('loop_count', 'NOT_PRESENT')} | "
                f"loop_count_type={type(state_dict.get('loop_count'))}"
            )

            # Create a safe evaluation context
            # Use StateWrapper to support dot notation access (e.g., state.loop_count)
            wrapped_state = StateWrapper(state_dict)
            eval_context = {
                "state": wrapped_state,
                "context": state.get("context", {}),
                "messages": state.get("messages", []),
                "current_node": state.get("current_node"),
                "loop_count": state.get("loop_count", 0),
                "route_decision": state.get("route_decision"),
            }

            # Debug: Test attribute access before evaluation
            try:
                loop_count_attr = getattr(wrapped_state, "loop_count", "NOT_FOUND")
                logger.debug(
                    f"[ConditionNodeExecutor] StateWrapper attribute test | "
                    f"node_id={self.node_id} | wrapped_state.loop_count={loop_count_attr} | "
                    f"type={type(loop_count_attr)}"
                )
            except Exception as attr_e:
                logger.warning(
                    f"[ConditionNodeExecutor] Failed to access loop_count attribute | "
                    f"node_id={self.node_id} | error={attr_e}"
                )

            # Evaluate the expression
            result = eval(self.expression, {"__builtins__": {}}, eval_context)
            bool_result = bool(result)

            # Print expression and result for debugging
            logger.info(
                f"[ConditionNodeExecutor] Expression evaluation | "
                f"node_id={self.node_id} | expression='{self.expression}' | result={bool_result} | raw_result={result}"
            )

            return bool_result
        except Exception as e:
            logger.error(
                f"[ConditionNodeExecutor] Error evaluating expression '{self.expression}' | "
                f"node_id={self.node_id} | error={type(e).__name__}: {e}"
            )
            return False

    async def __call__(self, state: GraphState) -> Union[Dict[str, Any], RouteKey, Command]:
        """Evaluate the condition and return route decision."""
        start_time = time.time()

        # Check if Command mode is enabled
        data = self.node.data or {}
        config = data.get("config", {})
        use_command_mode = config.get("useCommandMode", False) and COMMAND_AVAILABLE

        logger.info(
            f"[ConditionNodeExecutor] >>> Evaluating condition node '{self.node_id}' | "
            f"expression='{self.expression}' | command_mode={use_command_mode}"
        )

        condition_result = self._evaluate_expression(state)

        # Determine route key based on condition result
        if condition_result:
            route_key = self.handle_to_route_map.get("true", "true")
        else:
            route_key = self.handle_to_route_map.get("false", "false")

        elapsed_ms = (time.time() - start_time) * 1000
        label = self.trueLabel if condition_result else self.falseLabel
        logger.info(
            f"[ConditionNodeExecutor] <<< Condition evaluated | "
            f"node_id={self.node_id} | result={condition_result} | "
            f"route_key={route_key} | label={label} | elapsed={elapsed_ms:.2f}ms"
        )

        # Return Command object if Command mode is enabled
        if use_command_mode:
            true_goto = config.get("commandTrueGoto")
            false_goto = config.get("commandFalseGoto")

            goto_node = true_goto if condition_result else false_goto
            if goto_node:
                logger.debug(
                    f"[ConditionNodeExecutor] Returning Command with goto={goto_node} | "
                    f"node_id={self.node_id} | condition_result={condition_result}"
                )
                return Command(
                    update={
                        "current_node": self.node_id,
                        "route_decision": route_key,
                        "route_history": [route_key],
                    },
                    goto=goto_node,
                )

        # Default: return dict (for conditional edges)
        return {
            "current_node": self.node_id,
            "route_decision": route_key,
            "route_history": [route_key],
        }


class RouterNodeExecutor:
    """Executor for a Router node in the graph.

    Evaluates multiple routing rules and returns a route_key that maps to
    React Flow's source_handle_id. This ensures UI connections match logical routing.
    """

    STATE_READS: tuple = ("*",)  # Rule expressions can reference any field
    STATE_WRITES: tuple = ("route_decision", "route_history")

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.rules = self._get_rules()

        # Pre-validate all rule conditions for safety
        for rule in self.rules:
            condition = rule.get("condition", "")
            if condition and not validate_condition_expression(condition):
                raise ValueError(
                    f"Invalid condition expression in router rule '{rule.get('id', 'unknown')}': {condition}"
                )

        # Map handle IDs to route keys (set during graph building)
        self.handle_to_route_map: Dict[str, str] = {}

    def _get_rules(self) -> List[Dict[str, Any]]:
        """Extract routing rules from node configuration.

        Rules are sorted by priority if available (lower priority number = higher priority).
        """
        data = self.node.data or {}
        config = data.get("config", {})
        rules = config.get("routes", [])

        # Sort by priority (ascending, None treated as lowest priority/infinity)
        def get_priority(r):
            p = r.get("priority")
            return float("inf") if p is None else int(p)

        return sorted(rules, key=get_priority)

    def set_handle_to_route_map(self, handle_map: Dict[str, str]) -> None:
        """Set the mapping from React Flow handle IDs to route keys."""
        self.handle_to_route_map = handle_map

    async def __call__(self, state: GraphState) -> Union[Dict[str, Any], RouteKey]:
        """Evaluate rules and return route decision."""
        start_time = time.time()
        logger.info(f"[RouterNodeExecutor] >>> Evaluating router node '{self.node_id}' | rules_count={len(self.rules)}")

        # Create evaluation context once
        state_dict = dict(state)
        wrapped_state = StateWrapper(state_dict)
        eval_context = {
            "state": wrapped_state,
            "context": state.get("context", {}),
            "messages": state.get("messages", []),
            "current_node": state.get("current_node"),
            "loop_count": state.get("loop_count", 0),
        }

        selected_route_key = None
        data = self.node.data or {}
        config = data.get("config", {})
        default_route = config.get("defaultRoute", "default")

        # Evaluate rules in order
        for rule in self.rules:
            condition = rule.get("condition")
            target_edge_key = rule.get("targetEdgeKey")

            if not condition or not target_edge_key:
                continue

            try:
                result = eval(condition, {"__builtins__": {}}, eval_context)
                if bool(result):
                    selected_route_key = target_edge_key
                    logger.info(
                        f"[RouterNodeExecutor] Matched rule '{rule.get('label')}' | "
                        f"condition='{condition}' | route_key={selected_route_key}"
                    )
                    break
            except Exception as e:
                logger.error(
                    f"[RouterNodeExecutor] Error evaluating rule '{rule.get('id')}' | "
                    f"condition='{condition}' | error={e}"
                )

        # Fallback to default if no rules matched
        if not selected_route_key:
            selected_route_key = default_route
            logger.info(f"[RouterNodeExecutor] No rules matched, using default route: {selected_route_key}")

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[RouterNodeExecutor] <<< Router complete | "
            f"node_id={self.node_id} | route_decision={selected_route_key} | elapsed={elapsed_ms:.2f}ms"
        )

        return {
            "current_node": self.node_id,
            "route_decision": selected_route_key,
            "route_history": [selected_route_key],
        }


class LoopConditionNodeExecutor:
    """Executor for a Loop Condition node in the graph.

    Manages loop state (counts, iterations) and implements standard loop logic:
    - while: check condition before execution
    - do-while: check condition after execution (implemented via graph structure)
    - for-each: iterate over a list in state
    """

    STATE_READS: tuple = ("loop_count", "loop_condition_met", "context", "loop_states")
    STATE_WRITES: tuple = (
        "loop_count",
        "loop_condition_met",
        "loop_states",
        "context",
    )  # context allows item injection

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id

        data = self.node.data or {}
        self.config = data.get("config", {})
        self.condition_type = self.config.get("conditionType", "while")
        self.max_iterations = int(self.config.get("maxIterations", 100))
        self.list_variable = self.config.get("listVariable")
        self.condition = self.config.get("condition", "")

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Evaluate loop condition and update loop state."""
        start_time = time.time()

        # Get current loop state for this specific node
        all_loop_states = state.get("loop_states", {}) or {}
        loop_state = all_loop_states.get(self.node_id, {})

        iteration_count = loop_state.get("iteration_count", 0)

        logger.info(
            f"[LoopNodeExecutor] >>> Evaluating loop '{self.node_id}' | "
            f"type={self.condition_type} | iteration={iteration_count}/{self.max_iterations}"
        )

        # Safety check: Max iterations
        if iteration_count >= self.max_iterations:
            logger.warning(
                f"[LoopNodeExecutor] Max iterations ({self.max_iterations}) reached for node '{self.node_id}'. Exiting loop."
            )
            return self._exit_loop(state, loop_state, "max_iterations_reached")

        should_continue = False
        loop_item = None

        try:
            if self.condition_type == "forEach":
                if not self.list_variable:
                    raise ValueError("List variable not configured for forEach loop")

                # Get list from state
                # Use StateWrapper to handle dot notation if list_variable is like "data.items"
                state_wrapper = StateWrapper(dict(state))

                # Simple recursive get helper for dot notation
                items = self._get_value_by_path(state_wrapper, self.list_variable)

                if not isinstance(items, (list, tuple)):
                    logger.warning(f"[LoopNodeExecutor] Variable '{self.list_variable}' is not a list: {type(items)}")
                    items = []

                if iteration_count < len(items):
                    should_continue = True
                    loop_item = items[iteration_count]
                    # Inject current item into context/state
                    # Convention: inject as 'loop_item' or maybe config allows naming it
                    # For now, we'll put it in context under 'loop_item'
                else:
                    should_continue = False

            elif self.condition_type in ("while", "doWhile"):
                # Evaluate python condition
                if not self.condition:
                    should_continue = False  # No condition = stop
                else:
                    # Eval context
                    # Use StateWrapper
                    wrapped_state = StateWrapper(dict(state))
                    eval_context = {
                        "state": wrapped_state,
                        "context": state.get("context", {}),
                        "loop_count": iteration_count,  # Use local count
                        "loop_item": state.get("context", {}).get("loop_item"),
                    }
                    result = eval(self.condition, {"__builtins__": {}}, eval_context)
                    should_continue = bool(result)

            else:
                logger.warning(f"[LoopNodeExecutor] Unknown loop type: {self.condition_type}")
                should_continue = False

        except Exception as e:
            logger.error(f"[LoopNodeExecutor] Error evaluating loop logic: {e}")
            should_continue = False

        # Update state based on decision
        if should_continue:
            new_iteration_count = iteration_count + 1

            # Update loop_states
            new_loop_states = all_loop_states.copy()
            new_loop_states[self.node_id] = {"iteration_count": new_iteration_count, "active": True}

            updates = {
                "loop_states": new_loop_states,
                "loop_count": new_iteration_count,  # Update global loop count if needed, but local is better
                "loop_condition_met": True,
                "current_node": self.node_id,
                "route_decision": "continue_loop",
                "route_history": ["continue_loop"],
            }

            # If forEach, inject item
            if loop_item is not None:
                current_context = state.get("context", {}).copy()
                current_context["loop_item"] = loop_item
                updates["context"] = current_context

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[LoopNodeExecutor] <<< Continuing loop | iteration={new_iteration_count} | elapsed={elapsed_ms:.2f}ms"
            )
            return updates
        else:
            return self._exit_loop(state, loop_state, "condition_false")

    def _exit_loop(self, state: GraphState, loop_state: Dict[str, Any], reason: str) -> Dict[str, Any]:
        """Helper to construct exit state."""
        all_loop_states = state.get("loop_states", {}) or {}
        new_loop_states = all_loop_states.copy()

        # Reset or mark inactive? Usually reset for next run, but maybe keep history
        new_loop_states[self.node_id] = {
            "iteration_count": 0,  # Reset for next time this node is entered?
            # Or keep it? If we re-enter deeply, we might want 0.
            # For now, let's mark inactive and maybe reset.
            "active": False,
            "last_exit_reason": reason,
        }

        logger.info(f"[LoopNodeExecutor] <<< Exiting loop | reason={reason}")

        return {
            "loop_states": new_loop_states,
            "loop_condition_met": False,
            "current_node": self.node_id,
            "route_decision": "exit_loop",
            "route_history": ["exit_loop"],
        }

    def _get_value_by_path(self, obj: Any, path: str) -> Any:
        """Helper to get value from dot notation."""
        parts = path.split(".")
        current = obj
        for part in parts:
            if isinstance(current, StateWrapper):
                current = getattr(current, part, None)
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
            if current is None:
                return None
        return current


class ConditionAgentNodeExecutor:
    """Executor for a Condition Agent node in the graph.

    Uses an LLM to evaluate the state against an instruction and multiple routing options,
    returning a route decision.
    """

    STATE_READS: tuple = ("*",)
    STATE_WRITES: tuple = ("route_decision", "route_history")

    def __init__(
        self,
        node: GraphNode,
        node_id: str,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[Any] = None,
        checkpointer: Optional[Any] = None,
        resolved_model: Optional[Any] = None,
        builder: Optional[Any] = None,
    ):
        self.node = node
        self.node_id = node_id
        self.resolved_model = resolved_model

        data = self.node.data or {}
        config = data.get("config", {})
        self.instruction = config.get("instruction", "Analyze the available context and select the best option.")
        self.options = config.get("options", [])

        if not self.options:
            logger.warning(
                f"[ConditionAgentNodeExecutor] No options provided for node '{node_id}', routing might fail."
            )

        self.handle_to_route_map: Dict[str, str] = {}

    def set_handle_to_route_map(self, handle_map: Dict[str, str]) -> None:
        """Set the mapping from React Flow handle IDs to route keys."""
        self.handle_to_route_map = handle_map

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Evaluate the LLM condition and return route decision."""
        start_time = time.time()

        if not self.resolved_model:
            logger.error(
                f"[ConditionAgentNodeExecutor] No resolved model available for node '{self.node_id}'. Cannot route."
            )
            return {
                "current_node": self.node_id,
            }

        valid_options = [opt for opt in self.options if opt]
        options_text = ", ".join([f"'{opt}'" for opt in valid_options])

        system_prompt = (
            f"You are a routing agent. Your task is to analyze the provided state/context "
            f"and choose exactly one of the following route options: [{options_text}].\n\n"
            f"Instruction: {self.instruction}\n\n"
            f"You must output ONLY the exact text of the chosen option, nothing else. "
            f"Do not include any explanations."
        )

        # Context serialization
        messages = state.get("messages", [])
        last_message = ""
        if messages:
            last_msg = messages[-1]
            last_message = getattr(last_msg, "content", str(last_msg))

        user_content = f"Latest message context:\n{last_message}\n\nPlease output the selected route option."

        from langchain_core.messages import HumanMessage, SystemMessage

        llm_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_content),
        ]

        logger.info(
            f"[ConditionAgentNodeExecutor] >>> Evaluating condition agent '{self.node_id}' with options: {valid_options}"
        )

        try:
            response = await self.resolved_model.ainvoke(llm_messages)
            decision = getattr(response, "content", str(response)).strip()

            # Remove possible quotes if model wraps it
            if decision.startswith("'") and decision.endswith("'"):
                decision = decision[1:-1]
            if decision.startswith('"') and decision.endswith('"'):
                decision = decision[1:-1]

            # Map selected option to route key (TargetEdgeKey is often identical to option label, handle mapping should exist)
            # Find the corresponding route_key from handle_map
            # The handle map uses Option name as key or target if we matched it up.
            route_key = self.handle_to_route_map.get(decision, decision)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[ConditionAgentNodeExecutor] <<< AI Condition evaluated | "
                f"node_id={self.node_id} | decision='{decision}' | "
                f"route_key='{route_key}' | elapsed={elapsed_ms:.2f}ms"
            )

            return {
                "current_node": self.node_id,
                "route_decision": route_key,
                "route_history": [route_key],
            }
        except Exception as e:
            logger.error(
                f"[ConditionAgentNodeExecutor] Error invoking LLM for routing | node_id={self.node_id} | error={e}"
            )
            # Fallback to first available option
            fallback_route = (
                self.handle_to_route_map.get(valid_options[0], valid_options[0]) if valid_options else "default"
            )
            return {
                "current_node": self.node_id,
                "route_decision": fallback_route,
                "route_history": [fallback_route],
            }
