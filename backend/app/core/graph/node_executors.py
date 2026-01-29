"""
Node Executors - Execute different types of nodes in the graph.

Each executor handles a specific node type (agent, condition, direct_reply, etc.)
and implements the execution logic for that node type.
"""

import ast
import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence, Union, cast

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable
from loguru import logger

try:
    from langgraph.types import Command

    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None  # type: ignore[assignment,misc]
    logger.warning("[NodeExecutors] langgraph.types.Command not available, Command mode disabled")

from app.core.agent.node_tools import resolve_tools_for_node
from app.core.agent.sample_agent import get_agent
from app.core.graph.graph_state import GraphState
from app.core.graph.route_types import RouteKey
from app.models.graph import GraphNode


def validate_condition_expression(expr: str) -> bool:
    """
    Pre-validate condition expression syntax and safety.

    Enhanced validation with better error handling and more permissive safe operations.

    Args:
        expr: Python expression string to validate

    Returns:
        True if expression is safe and syntactically valid, False otherwise
    """
    if not expr or not expr.strip():
        return False

    try:
        # Parse the expression to AST
        tree = ast.parse(expr, mode="eval")

        # Walk through all nodes and check for dangerous constructs
        for node in ast.walk(tree):
            # Check function calls
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    # Allow specific safe builtin functions
                    safe_functions = {
                        "len",
                        "str",
                        "int",
                        "float",
                        "bool",
                        "abs",
                        "min",
                        "max",
                        "sum",
                        "any",
                        "all",
                        "sorted",
                        "reversed",
                        "enumerate",
                        "range",
                        "list",
                        "dict",
                        "set",
                        "tuple",
                    }
                    if node.func.id not in safe_functions:
                        logger.warning(f"[ConditionValidator] Disallowed function call: {node.func.id}")
                        return False
                elif isinstance(node.func, ast.Attribute):
                    # Allow method calls on specific safe objects
                    if isinstance(node.func.value, ast.Name):
                        obj_name = node.func.value.id
                        method_name = node.func.attr

                        # Allow comprehensive methods on safe objects
                        safe_object_methods = {
                            "state": {"get", "keys", "values", "items", "__contains__", "__getitem__", "__len__"},
                            "context": {"get", "keys", "values", "items", "__contains__", "__getitem__", "__len__"},
                            "messages": {
                                "get",
                                "keys",
                                "values",
                                "items",
                                "__contains__",
                                "__getitem__",
                                "__len__",
                                "__iter__",
                            },
                            "loop_state": {"get", "keys", "values", "items", "__contains__", "__getitem__", "__len__"},
                            "loop_count": set(),  # Allow direct access to loop_count variable
                            "current_node": set(),  # Allow direct access to current_node variable
                        }

                        # Check if object is in safe list
                        if obj_name in safe_object_methods:
                            allowed_methods = safe_object_methods[obj_name]
                            # Allow all methods if set is empty (for variables), or specific methods
                            if not allowed_methods or method_name in allowed_methods:
                                continue

                        # Allow some safe operations on lists/dicts/strings
                        safe_container_methods = {
                            "append",
                            "extend",
                            "insert",
                            "remove",
                            "pop",
                            "clear",
                            "index",
                            "count",
                            "keys",
                            "values",
                            "items",
                            "get",
                            "__getitem__",
                            "__contains__",
                            "__len__",
                            "startswith",
                            "endswith",
                            "strip",
                            "split",
                            "join",
                            "upper",
                            "lower",
                            "replace",
                        }
                        if method_name in safe_container_methods:
                            continue

                        logger.warning(f"[ConditionValidator] Disallowed method call: {obj_name}.{method_name}")
                        return False
                    else:
                        # Allow chained calls like state.get('key', {}).get('subkey')
                        # This is more permissive but still safe
                        continue
                else:
                    logger.warning("[ConditionValidator] Unsupported call type")
                    return False

            # Disallow dangerous constructs
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                logger.warning(f"[ConditionValidator] Disallowed construct: {type(node).__name__}")
                return False

            # Disallow assignments and mutations
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
                logger.warning(f"[ConditionValidator] Disallowed mutation: {type(node).__name__}")
                return False

            # Disallow function definitions
            elif isinstance(node, (ast.FunctionDef, ast.Lambda)):
                logger.warning(f"[ConditionValidator] Disallowed function definition: {type(node).__name__}")
                return False

        return True
    except SyntaxError as e:
        logger.warning(f"[ConditionValidator] Syntax error in expression '{expr}': {e}")
        return False
    except Exception as e:
        logger.warning(f"[ConditionValidator] Unexpected error validating expression '{expr}': {e}")
        return False


class StateWrapper:
    """Wrapper that allows both dot notation and dict access to state.

    This class enables expressions like 'state.loop_count>1' to work,
    while still supporting dict-style access like 'state.get("loop_count")'.
    """

    def __init__(self, state_dict: Dict[str, Any]):
        self._state = state_dict
        # Set attributes for direct dot notation access
        for key, value in state_dict.items():
            if isinstance(value, dict):
                # Recursively wrap nested dictionaries
                setattr(self, key, StateWrapper(value))
            else:
                setattr(self, key, value)

    def __getattr__(self, name: str) -> Any:
        """Handle attribute access for keys that may not exist in the dict.

        This allows accessing optional fields like loop_count even if they
        weren't in the original dict when StateWrapper was created.
        """
        if name.startswith("_"):
            # Don't interfere with private attributes
            raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

        # Try to get from the underlying dict
        if name in self._state:
            value = self._state[name]
            # If it's a dict, wrap it (in case it was added after initialization)
            if isinstance(value, dict):
                return StateWrapper(value)
            return value

        # Return None for missing attributes (allows expressions like state.loop_count > 1)
        # This is safer than raising AttributeError for optional fields
        return None

    def get(self, key: str, default: Any = None) -> Any:
        """Support dict.get() method for backward compatibility."""
        return self._state.get(key, default)

    def __getitem__(self, key: str) -> Any:
        """Support dict[] access for backward compatibility."""
        return self._state[key]

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator."""
        return key in self._state

    def keys(self):
        """Support dict.keys() method."""
        return self._state.keys()

    def values(self):
        """Support dict.values() method."""
        return self._state.values()

    def items(self):
        """Support dict.items() method."""
        return self._state.items()

    def __len__(self) -> int:
        """Support len() function."""
        return len(self._state)


class AgentNodeExecutor:
    """
    Executor for an Agent node in the graph.

    Wraps a LangChain `create_agent` graph (tools + middleware) using the same
    implementation approach as `app.core.agent.sample_agent.get_agent`.
    """

    def __init__(
        self,
        node: GraphNode,
        node_id: str,
        *,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[str] = None,
        checkpointer: Optional[Any] = None,
        messages_window: int = 10,
        resolved_model: Optional[Any] = None,
        builder: Optional[Any] = None,
    ):
        self.node = node
        self.node_id = node_id
        self.system_prompt = self._get_system_prompt()
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.user_id = user_id
        self.checkpointer = checkpointer
        self.messages_window = messages_window
        self.resolved_model = resolved_model  # 保存解析的模型对象
        self.builder = builder  # BaseGraphBuilder instance for resolving middleware

        self._agent: Runnable | None = None
        self._agent_lock = asyncio.Lock()
        node_data = node.data or {}
        node_data.get("type") or node.type

    def _get_system_prompt(self) -> str:
        """Extract system prompt from node configuration."""
        if self.node.prompt:
            return self.node.prompt
        data = self.node.data or {}
        config = data.get("config", {})
        system_prompt = config.get("systemPrompt", "")
        prompt = config.get("prompt", "")
        result = system_prompt or prompt
        return str(result) if result is not None else ""

    async def _ensure_agent(self) -> Runnable:
        """Lazily create the underlying LangChain agent graph once per node."""
        if self._agent is not None:
            return self._agent
        async with self._agent_lock:
            if self._agent is not None:
                return self._agent

            node_tools = await resolve_tools_for_node(self.node, user_id=self.user_id)

            # 检查 node_tools 中是否有 ToolMetadata 对象
            if isinstance(node_tools, list):
                from app.core.tools.tool import ToolMetadata

                for i, tool in enumerate(node_tools):
                    if isinstance(tool, ToolMetadata):
                        logger.error(
                            f"[AgentNodeExecutor._ensure_agent] ERROR: ToolMetadata object found at index {i}! "
                            f"This should not happen. metadata: {tool}"
                        )

            # Resolve node-specific middleware (e.g., MemoryMiddleware, SkillMiddleware from node config)
            node_middleware = []
            if self.builder:
                try:
                    node_middleware = await self.builder.resolve_middleware_for_node(
                        node=self.node,
                        user_id=self.user_id,
                    )
                    if node_middleware:
                        logger.debug(
                            f"[AgentNodeExecutor._ensure_agent] Resolved {len(node_middleware)} middleware "
                            f"instance(s) for node '{self.node_id}'"
                        )
                except Exception as e:
                    logger.warning(
                        f"[AgentNodeExecutor._ensure_agent] Failed to resolve middleware for node '{self.node_id}': {e}"
                    )

            # 如果已经有解析的模型对象，直接使用它
            if self.resolved_model:
                logger.info(
                    f"[AgentNodeExecutor._ensure_agent] Using resolved model from node config | "
                    f"node_id={self.node_id} | model_type={type(self.resolved_model).__name__}"
                )
                # 使用解析的模型对象创建 agent
                self._agent = await get_agent(
                    model=self.resolved_model,
                    checkpointer=self.checkpointer,
                    user_id=self.user_id,
                    system_prompt=self.system_prompt or None,
                    tools=node_tools,
                    agent_name=self.node_id,
                    node_middleware=node_middleware,
                )
            else:
                # 如果没有解析的模型，使用参数创建（向后兼容）
                self._agent = await get_agent(
                    checkpointer=self.checkpointer,
                    llm_model=self.llm_model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    max_tokens=self.max_tokens,
                    user_id=self.user_id,
                    system_prompt=self.system_prompt or None,
                    tools=node_tools,
                    agent_name=self.node_id,
                    node_middleware=node_middleware,
                )
            # 打印 agent config 以确认 tags 是否带上
            try:
                logger.info(
                    f"[AgentNodeExecutor] Agent created | node_id={self.node_id} | config.tags={getattr(self._agent, 'config', {}).get('tags')}"
                )
            except Exception:
                pass
            return self._agent

    @staticmethod
    def _extract_new_messages(input_messages: List[BaseMessage], output_messages: Any) -> List[BaseMessage]:
        """Extract new messages from agent output."""
        if isinstance(output_messages, BaseMessage):
            return [output_messages]
        if not isinstance(output_messages, list):
            return [AIMessage(content=str(output_messages))]

        in_len = len(input_messages)
        out_len = len(output_messages)
        if out_len >= in_len:
            delta = output_messages[in_len:]
            if delta:
                return delta
            if output_messages:
                last = output_messages[-1]
                return [last] if isinstance(last, BaseMessage) else [AIMessage(content=str(last))]
            return [AIMessage(content="(no output)")]

        last = output_messages[-1] if output_messages else AIMessage(content="(no output)")
        return [last] if isinstance(last, BaseMessage) else [AIMessage(content=str(last))]

    async def __call__(self, state: GraphState) -> Union[Dict[str, Any], Command]:
        """Execute the agent node.

        Returns:
            Union[Dict[str, Any], Command]: State update dict or Command object for routing.
            Command mode can be enabled via node config: config.useCommandMode = true
        """
        start_time = time.time()
        messages_raw = state.get("messages", []) or []
        messages: List[BaseMessage] = list(messages_raw) if isinstance(messages_raw, (list, Sequence)) else []  # type: ignore[arg-type]

        # Check if Command mode is enabled for this node
        data = self.node.data or {}
        config = data.get("config", {})
        use_command_mode = config.get("useCommandMode", False) and COMMAND_AVAILABLE

        logger.info(
            f"[AgentNodeExecutor] >>> Executing node '{self.node_id}' | "
            f"input_messages_count={len(messages)} | command_mode={use_command_mode}"
        )

        input_messages = messages[-self.messages_window :] if self.messages_window > 0 else messages

        try:
            agent = await self._ensure_agent()

            result = await agent.ainvoke(
                {"messages": input_messages},
            )
            output_messages = result.get("messages") if isinstance(result, dict) else result
            new_messages = self._extract_new_messages(input_messages, output_messages)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[AgentNodeExecutor] <<< Node '{self.node_id}' completed | "
                f"elapsed={elapsed_ms:.2f}ms | new_messages={len(new_messages)}"
            )

            # Return Command object if Command mode is enabled
            if use_command_mode:
                # In Command mode, determine next node from config or use default routing
                goto_node = config.get("commandGoto")
                if goto_node:
                    logger.debug(
                        f"[AgentNodeExecutor] Returning Command with goto={goto_node} | node_id={self.node_id}"
                    )
                    return Command(
                        update={
                            "messages": new_messages,
                            "current_node": self.node_id,
                        },
                        goto=goto_node,
                    )

            # Default: return dict (backward compatible)
            return_dict = {
                "messages": new_messages,
                "current_node": self.node_id,
            }

            return return_dict
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[AgentNodeExecutor] !!! Error in node '{self.node_id}' | "
                f"elapsed={elapsed_ms:.2f}ms | error={type(e).__name__}: {e}"
            )
            error_message = AIMessage(content=f"Error in node {self.node_id}: {str(e)}")

            # In Command mode, can route to error handler node
            if use_command_mode:
                error_goto = config.get("commandErrorGoto")
                if error_goto:
                    return Command(
                        update={
                            "messages": [error_message],
                            "current_node": self.node_id,
                        },
                        goto=error_goto,
                    )

            return {
                "messages": [error_message],
                "current_node": self.node_id,
            }


class ConditionNodeExecutor:
    """Executor for a Condition node in the graph.

    Evaluates a condition expression and returns a route decision.
    The returned route_key will be used by LangGraph's conditional edges.
    """

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
        """Evaluate the condition and return route decision.

        Returns:
            Union[Dict[str, Any], RouteKey, Command]:
            - Dict with route_decision (default mode, for conditional edges)
            - RouteKey (when used as router function)
            - Command object (if Command mode enabled)
        """
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
        # Default: "true" for True, "false" for False
        # Can be customized via handle_to_route_map
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
            # Get target nodes from config
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


class DirectReplyNodeExecutor:
    """Executor for a Direct Reply node in the graph."""

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.template = self._get_template()

    def _get_template(self) -> str:
        """Extract template from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        template = config.get("template", "")
        return str(template) if template is not None else ""
        return config.get("template", "")

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Return the template message."""
        content = self.template
        context = state.get("context", {})
        for key, value in context.items():
            content = content.replace(f"{{{{{key}}}}}", str(value))

        return {
            "messages": [AIMessage(content=content)],
            "current_node": self.node_id,
        }


class RouterNodeExecutor:
    """Executor for a Router node in the graph.

    Evaluates multiple routing rules and returns a route_key that maps to
    React Flow's source_handle_id. This ensures UI connections match logical routing.
    """

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
        if not isinstance(rules, list):
            return []
        # Sort by priority if available (lower priority number = higher priority)
        if rules and isinstance(rules[0].get("priority"), int):
            rules = sorted(rules, key=lambda r: r.get("priority", 999))
        return rules

    def set_handle_to_route_map(self, handle_map: Dict[str, str]) -> None:
        """Set the mapping from React Flow handle IDs to route keys."""
        self.handle_to_route_map = handle_map

    def _evaluate_rule(self, rule: Dict[str, Any], state: GraphState) -> bool:
        """Evaluate a single routing rule condition."""
        condition = rule.get("condition", "")
        if not condition:
            return False

        try:
            # Create a safe evaluation context
            # Use StateWrapper to support dot notation access (e.g., state.loop_count)
            eval_context = {
                "state": StateWrapper(dict(state)),
                "context": state.get("context", {}),
                "messages": state.get("messages", []),
                "current_node": state.get("current_node"),
                "loop_count": state.get("loop_count", 0),
                "route_decision": state.get("route_decision"),
            }

            # Evaluate the condition
            result = eval(condition, {"__builtins__": {}}, eval_context)
            return bool(result)
        except Exception as e:
            logger.error(
                f"[RouterNodeExecutor] Error evaluating rule condition '{condition}' | "
                f"node_id={self.node_id} | error={type(e).__name__}: {e}"
            )
            return False

    async def __call__(self, state: GraphState) -> Union[RouteKey, Command]:
        """Evaluate routing rules and return route_key or Command.

        Returns:
            Union[RouteKey, Command]:
            - RouteKey: Route key that maps to source_handle_id in React Flow edges (default mode)
            - Command: Command object with goto target (if Command mode enabled)
        """
        start_time = time.time()

        # Check if Command mode is enabled
        data = self.node.data or {}
        config = data.get("config", {})
        use_command_mode = config.get("useCommandMode", False) and COMMAND_AVAILABLE
        default_route = config.get("defaultRoute", "default")

        logger.info(
            f"[RouterNodeExecutor] >>> Evaluating router node '{self.node_id}' | "
            f"rules_count={len(self.rules)} | command_mode={use_command_mode}"
        )

        # Evaluate rules in order, return first matching route_key
        for rule in self.rules:
            if self._evaluate_rule(rule, state):
                # Primary: Use targetEdgeKey from rule configuration
                route_key = rule.get("targetEdgeKey")
                source_handle_id = rule.get("source_handle_id")

                # Fallback: If no targetEdgeKey but have handle mapping, use it
                # This handles legacy cases where edge route_key differs from rule targetEdgeKey
                if not route_key and source_handle_id and source_handle_id in self.handle_to_route_map:
                    route_key = self.handle_to_route_map[source_handle_id]

                # Final fallback: Use default route
                if not route_key:
                    route_key = default_route

                elapsed_ms = (time.time() - start_time) * 1000
                logger.info(
                    f"[RouterNodeExecutor] <<< Route selected | "
                    f"node_id={self.node_id} | route_key={route_key} | "
                    f"rule_target={rule.get('targetEdgeKey')} | handle_mapping={source_handle_id} | "
                    f"elapsed={elapsed_ms:.2f}ms"
                )

                # Return Command if Command mode is enabled
                if use_command_mode:
                    # Try to get target node from rule config or route mapping
                    goto_node = rule.get("commandGoto")
                    if not goto_node and route_key:
                        # Try to find target node from conditional_map (would need access to it)
                        # For now, use route_key as goto (assuming node names match route keys)
                        goto_node = route_key

                    if goto_node:
                        logger.debug(
                            f"[RouterNodeExecutor] Returning Command with goto={goto_node} | "
                            f"node_id={self.node_id} | route_key={route_key}"
                        )
                        return Command(
                            update={
                                "current_node": self.node_id,
                                "route_decision": route_key,
                                "route_history": [route_key],
                            },
                            goto=goto_node,
                        )

                return str(route_key) if route_key is not None else ""

        # No rule matched, return default
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[RouterNodeExecutor] <<< No rule matched, using default | "
            f"node_id={self.node_id} | route_key={default_route} | elapsed={elapsed_ms:.2f}ms"
        )

        # Return Command if Command mode is enabled
        if use_command_mode:
            default_goto = config.get("commandDefaultGoto", default_route)
            if default_goto:
                return Command(
                    update={
                        "current_node": self.node_id,
                        "route_decision": default_route,
                        "route_history": [default_route],
                    },
                    goto=default_goto,
                )

        return str(default_route) if default_route is not None else ""


class ToolNodeExecutor:
    """Executor for a Tool node in the graph.

    Executes a tool with parameters mapped from state.
    """

    def __init__(self, node: GraphNode, node_id: str, user_id: Optional[str] = None):
        self.node = node
        self.node_id = node_id
        self.user_id = user_id
        self.tool_name = self._get_tool_name()
        self.input_mapping = self._get_input_mapping()
        self._tool: Optional[Any] = None

    def _get_tool_name(self) -> str:
        """Extract tool name from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        tool_name = config.get("tool_name", "")
        return str(tool_name) if tool_name is not None else ""

    def _get_input_mapping(self) -> Dict[str, str]:
        """Extract input parameter mapping from node configuration.

        Returns:
            Dict mapping tool parameter names to state access expressions.
            Example: {"query": "state.context.get('user_query')"}
        """
        data = self.node.data or {}
        config = data.get("config", {})
        result = config.get("input_mapping", {})
        return result if isinstance(result, dict) else {}  # type: ignore[return-value]

    async def _resolve_tool(self) -> Any:
        """Resolve the tool instance from the registry."""
        if self._tool is not None:
            return self._tool

        if not self.tool_name:
            logger.error(f"[ToolNodeExecutor] No tool_name specified for node '{self.node_id}'")
            return None

        try:
            from app.core.tools.tool_registry import get_global_registry

            registry = get_global_registry()
            tool = registry.get_tool(self.tool_name)

            if not tool:
                logger.error(
                    f"[ToolNodeExecutor] Tool '{self.tool_name}' not found in registry | node_id={self.node_id}"
                )
                return None

            self._tool = tool
            return tool
        except Exception as e:
            logger.error(
                f"[ToolNodeExecutor] Error resolving tool '{self.tool_name}' | "
                f"node_id={self.node_id} | error={type(e).__name__}: {e}"
            )
            return None

    def _map_inputs(self, state: GraphState) -> Dict[str, Any]:
        """Map state values to tool input parameters."""
        tool_inputs = {}
        eval_context = {
            "state": dict(state),
            "context": state.get("context", {}),
        }

        for param_name, expression in self.input_mapping.items():
            try:
                value = eval(expression, {"__builtins__": {}}, eval_context)
                tool_inputs[param_name] = value
            except Exception as e:
                logger.warning(
                    f"[ToolNodeExecutor] Error evaluating input mapping '{expression}' | "
                    f"param={param_name} | node_id={self.node_id} | error={type(e).__name__}: {e}"
                )

        return tool_inputs

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute the tool node."""
        start_time = time.time()
        logger.info(f"[ToolNodeExecutor] >>> Executing tool node '{self.node_id}' | tool_name={self.tool_name}")

        try:
            tool = await self._resolve_tool()
            if not tool:
                error_msg = f"Tool '{self.tool_name}' not found"
                logger.error(f"[ToolNodeExecutor] {error_msg} | node_id={self.node_id}")
                return {
                    "current_node": self.node_id,
                    "messages": [AIMessage(content=f"Error: {error_msg}")],
                }

            # Map inputs from state
            tool_inputs = self._map_inputs(state)
            logger.debug(f"[ToolNodeExecutor] Tool inputs mapped | node_id={self.node_id} | inputs={tool_inputs}")

            # Execute the tool
            if hasattr(tool, "ainvoke"):
                result = await tool.ainvoke(tool_inputs)
            elif hasattr(tool, "invoke"):
                result = tool.invoke(tool_inputs)
            else:
                # Try calling directly
                result = tool(**tool_inputs)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"[ToolNodeExecutor] <<< Tool executed | node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms")

            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=f"Tool '{self.tool_name}' executed: {str(result)}")],
                "tool_output": [result],
            }
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[ToolNodeExecutor] !!! Error executing tool | "
                f"node_id={self.node_id} | tool_name={self.tool_name} | "
                f"elapsed={elapsed_ms:.2f}ms | error={type(e).__name__}: {e}"
            )
            error_message = AIMessage(content=f"Error executing tool '{self.tool_name}': {str(e)}")
            return {
                "current_node": self.node_id,
                "messages": [error_message],
            }


class FunctionNodeExecutor:
    """Executor for a Function node in the graph.

    Executes custom Python code or a predefined function.
    WARNING: Code execution should be sandboxed in production.
    """

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.function_code = self._get_function_code()
        self.function_name = self._get_function_name()

    def _get_function_code(self) -> str:
        """Extract function code from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        function_code = config.get("function_code", "")
        return str(function_code) if function_code is not None else ""

    def _get_function_name(self) -> Optional[str]:
        """Extract predefined function name from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        function_name = config.get("function_name")
        return str(function_name) if function_name is not None else None

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute the function node."""
        start_time = time.time()
        logger.info(
            f"[FunctionNodeExecutor] >>> Executing function node '{self.node_id}' | "
            f"has_code={bool(self.function_code)} | function_name={self.function_name}"
        )

        try:
            result = {}

            if self.function_name:
                # Execute predefined function from registry
                from app.core.graph.function_registry import FunctionRegistry

                func = FunctionRegistry.get(self.function_name)
                if func:
                    try:
                        # Execute with state as first argument
                        func_result = func(state, **state.get("context", {}))
                        result = (
                            func_result
                            if isinstance(func_result, dict)
                            else {"result": func_result, "status": "success"}
                        )
                    except Exception as e:
                        logger.error(
                            f"[FunctionNodeExecutor] Error executing predefined function '{self.function_name}' | "
                            f"error={type(e).__name__}: {e}"
                        )
                        result = {"status": "error", "error_msg": str(e)}
                else:
                    logger.warning(
                        f"[FunctionNodeExecutor] Predefined function '{self.function_name}' not found in registry"
                    )
                    result = {"status": "error", "error_msg": f"Function '{self.function_name}' not found"}
            elif self.function_code:
                # Execute custom code with sandboxing
                from app.core.graph.sandbox_executor import SandboxExecutor

                execution_context = {
                    "state": state,
                    "context": state.get("context", {}),
                    "messages": state.get("messages", []),
                }

                # Use sandbox executor for safe execution
                result = SandboxExecutor.execute_safe(self.function_code, execution_context)

                # Ensure result is a dict
                if not isinstance(result, dict):
                    result = {"result": result, "status": "success"}
            else:
                result = {"status": "error", "error_msg": "No function code or name provided"}

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[FunctionNodeExecutor] <<< Function executed | node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms"
            )

            return {
                "current_node": self.node_id,
                "function_results": [result],
            }
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[FunctionNodeExecutor] !!! Error executing function | "
                f"node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms | "
                f"error={type(e).__name__}: {e}"
            )
            return {
                "current_node": self.node_id,
                "function_results": [{"status": "error", "error_msg": str(e)}],
            }


def update_loop_state(
    state: GraphState,
    loop_node_id: str,
    updates: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Helper function to update scoped loop state.

    Args:
        state: Current graph state
        loop_node_id: ID of the loop node
        updates: Dictionary of updates to apply to loop state

    Returns:
        State update dictionary with updated loop_states
    """
    loop_states = state.get("loop_states", {})
    loop_state = loop_states.get(loop_node_id, {}).copy()
    loop_state.update(updates)

    updated_loop_states = loop_states.copy()
    updated_loop_states[loop_node_id] = loop_state

    return {"loop_states": updated_loop_states}


def increment_loop_count(
    state: GraphState,
    loop_node_id: str,
) -> Dict[str, Any]:
    """
    Helper function to increment loop count in scoped state.

    Args:
        state: Current graph state
        loop_node_id: ID of the loop node

    Returns:
        State update dictionary with incremented loop_count
    """
    loop_states = state.get("loop_states", {})
    loop_state = loop_states.get(loop_node_id, {})
    current_count = loop_state.get("loop_count", 0)

    return update_loop_state(state, loop_node_id, {"loop_count": current_count + 1})


class LoopConditionNodeExecutor:
    """Executor for a Loop Condition node in the graph.

    Evaluates loop condition and returns 'continue_loop' or 'exit_loop'.
    Manages loop count in scoped state to avoid conflicts with parallel loops.

    Supports different loop types:
    - forEach: Iterate over a list variable
    - while: Check condition first, then execute
    - doWhile: Execute first, then check condition
    """

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        data = self.node.data or {}
        config = data.get("config", {})

        # Loop Condition node configuration fields
        self.conditionType = config.get("conditionType", "while")  # forEach/while/doWhile
        self.listVariable = config.get("listVariable", "items")  # For forEach mode
        self.condition = config.get("condition", "False")  # For while/doWhile
        self.maxIterations = config.get("maxIterations", 10)  # Maximum iterations

        # Pre-validate condition expression for safety (only for while/doWhile)
        if self.conditionType in ["while", "doWhile"] and self.condition:
            if not validate_condition_expression(self.condition):
                raise ValueError(f"Invalid loop condition expression in node '{node_id}': {self.condition}")

    def _evaluate_condition(self, state: GraphState) -> bool:
        """Evaluate the loop condition using scoped state."""
        if not self.condition:
            return False

        try:
            # Get scoped loop state for this node
            loop_states = state.get("loop_states", {})
            loop_state = loop_states.get(self.node_id, {})

            # Create evaluation context with scoped state
            # Use StateWrapper to support dot notation access (e.g., state.loop_count)
            eval_context = {
                "state": StateWrapper(dict(state)),
                "context": state.get("context", {}),
                "loop_count": loop_state.get("loop_count", 0),
                "loop_state": StateWrapper(loop_state) if loop_state else {},
            }

            result = eval(self.condition, {"__builtins__": {}}, eval_context)
            return bool(result)
        except Exception as e:
            logger.error(
                f"[LoopConditionNodeExecutor] Error evaluating condition | "
                f"node_id={self.node_id} | error={type(e).__name__}: {e}"
            )
            return False

    async def __call__(self, state: GraphState) -> str:
        """Evaluate loop condition and return route decision.

        Supports different loop types:
        - forEach: Iterate over list variable, continue until list is exhausted
        - while: Check condition first, then execute
        - doWhile: Execute first, then check condition

        Returns:
            'continue_loop' if condition is met and max iterations not reached
            'exit_loop' otherwise
        """
        start_time = time.time()

        # Get scoped loop state
        loop_states = state.get("loop_states", {})
        loop_state = loop_states.get(self.node_id, {})
        current_count = loop_state.get("loop_count", 0)

        logger.info(
            f"[LoopConditionNodeExecutor] >>> Evaluating loop condition | "
            f"node_id={self.node_id} | conditionType={self.conditionType} | "
            f"loop_count={current_count} | maxIterations={self.maxIterations}"
        )

        # Check max iterations (safety limit for all loop types)
        if current_count >= self.maxIterations:
            logger.warning(
                f"[LoopConditionNodeExecutor] Max iterations reached | "
                f"node_id={self.node_id} | count={current_count} | max={self.maxIterations}"
            )
            return "exit_loop"

        # Handle different loop types
        if self.conditionType == "forEach":
            # For forEach: check if there are more items to process
            items = state.get(self.listVariable, [])
            if not isinstance(items, list):
                logger.warning(
                    f"[LoopConditionNodeExecutor] forEach: listVariable '{self.listVariable}' "
                    f"is not a list, got {type(items).__name__}"
                )
                return "exit_loop"

            # Continue if there are more items to process
            # Note: The actual iteration index should be tracked in loop_state
            current_index = loop_state.get("current_index", 0)
            condition_met = current_index < len(items)

            logger.info(
                f"[LoopConditionNodeExecutor] forEach: current_index={current_index} | "
                f"total_items={len(items)} | condition_met={condition_met}"
            )

        elif self.conditionType == "doWhile":
            # For doWhile: condition is evaluated after execution
            # On first call, always continue (execute first)
            if current_count == 0:
                condition_met = True
                logger.info("[LoopConditionNodeExecutor] doWhile: First iteration, executing loop body")
            else:
                # After first execution, evaluate condition
                condition_met = self._evaluate_condition(state)
                logger.info(f"[LoopConditionNodeExecutor] doWhile: After execution, condition_met={condition_met}")
        else:
            # Default: while loop - check condition first
            condition_met = self._evaluate_condition(state)

        route_decision = "continue_loop" if condition_met else "exit_loop"

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[LoopConditionNodeExecutor] <<< Loop condition evaluated | "
            f"node_id={self.node_id} | conditionType={self.conditionType} | "
            f"condition_met={condition_met} | route={route_decision} | elapsed={elapsed_ms:.2f}ms"
        )

        return route_decision


class AggregatorNodeExecutor:
    """Executor for an Aggregator node in the graph (Fan-In).

    Waits for all upstream nodes to complete and aggregates their results.
    Supports error handling strategies: fail_fast or best_effort.
    """

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.error_strategy = self._get_error_strategy()

    def _get_error_strategy(self) -> str:
        """Extract error handling strategy from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        error_strategy = config.get("error_strategy", "fail_fast")  # 'fail_fast' or 'best_effort'
        return str(error_strategy) if error_strategy is not None else "fail_fast"

    def _aggregate_results(self, state: GraphState) -> Dict[str, Any]:
        """Aggregate results from parallel branches."""
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

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Aggregate results from all upstream nodes."""
        start_time = time.time()
        logger.info(
            f"[AggregatorNodeExecutor] >>> Aggregating results | "
            f"node_id={self.node_id} | strategy={self.error_strategy}"
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


# ==================== Standard Node Library ====================


class JSONParserNodeExecutor:
    """JSON parser and transformer node.

    Supports:
    - JSONPath queries
    - JSON Schema validation (optional)
    - JSON transformation
    """

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.jsonpath_query = self._get_jsonpath_query()
        self.schema_validation = self._get_schema_validation()

    def _get_jsonpath_query(self) -> Optional[str]:
        """Extract JSONPath query from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        query = config.get("jsonpath_query")
        return str(query) if query is not None else ""

    def _get_schema_validation(self) -> Optional[Dict[str, Any]]:
        """Extract JSON Schema for validation."""
        data = self.node.data or {}
        config = data.get("config", {})
        schema = config.get("json_schema")
        return schema if isinstance(schema, dict) else None

    def _parse_json(self, input_data: Any) -> Any:
        """Parse JSON from various input formats."""
        if isinstance(input_data, str):
            import json

            try:
                return json.loads(input_data)
            except json.JSONDecodeError:
                logger.warning(f"[JSONParserNodeExecutor] Invalid JSON string: {input_data[:100]}")
                return None
        elif isinstance(input_data, dict):
            return input_data
        else:
            return input_data

    def _apply_jsonpath(self, data: Any, query: str) -> Any:
        """Apply JSONPath query to data."""
        try:
            from jsonpath_ng import parse

            jsonpath_expr = parse(query)
            matches = [match.value for match in jsonpath_expr.find(data)]
            return matches[0] if len(matches) == 1 else matches
        except ImportError:
            logger.warning("[JSONParserNodeExecutor] jsonpath-ng not installed, skipping JSONPath query")
            return data
        except Exception as e:
            logger.error(f"[JSONParserNodeExecutor] Error applying JSONPath '{query}' | error={type(e).__name__}: {e}")
            return data

    def _validate_schema(self, data: Any, schema: Dict[str, Any]) -> bool:
        """Validate data against JSON Schema."""
        try:
            import jsonschema

            jsonschema.validate(instance=data, schema=schema)
            return True
        except ImportError:
            logger.warning("[JSONParserNodeExecutor] jsonschema not installed, skipping validation")
            return True
        except Exception as e:
            logger.error(f"[JSONParserNodeExecutor] Schema validation failed | error={type(e).__name__}: {e}")
            return False

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute JSON parser node."""
        start_time = time.time()
        logger.info(f"[JSONParserNodeExecutor] >>> Executing JSON parser node '{self.node_id}'")

        try:
            # Get input data from state
            context = state.get("context", {})
            input_data = context.get("json_input") or context.get("input")

            if input_data is None:
                # Try to get from last message
                messages = cast(list, state.get("messages", []))
                if messages:
                    last_message = messages[-1]
                    if hasattr(last_message, "content"):
                        input_data = last_message.content

            if input_data is None:
                return {
                    "current_node": self.node_id,
                    "messages": [AIMessage(content="No input data found for JSON parsing")],
                }

            # Parse JSON
            parsed_data = self._parse_json(input_data)
            if parsed_data is None:
                return {
                    "current_node": self.node_id,
                    "messages": [AIMessage(content="Failed to parse JSON")],
                }

            # Apply JSONPath if specified
            if self.jsonpath_query:
                parsed_data = self._apply_jsonpath(parsed_data, self.jsonpath_query)

            # Validate schema if specified
            if self.schema_validation:
                if not self._validate_schema(parsed_data, self.schema_validation):
                    return {
                        "current_node": self.node_id,
                        "messages": [AIMessage(content="JSON Schema validation failed")],
                    }

            # Store result in context
            import json

            result_str = json.dumps(parsed_data, ensure_ascii=False, indent=2)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[JSONParserNodeExecutor] <<< JSON parser completed | "
                f"node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms"
            )

            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=f"JSON parsed: {result_str[:200]}...")],
                "context": {"json_output": parsed_data},
            }
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[JSONParserNodeExecutor] !!! Error in JSON parser | "
                f"node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms | "
                f"error={type(e).__name__}: {e}"
            )
            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=f"JSON parser error: {str(e)}")],
            }


class HttpRequestNodeExecutor:
    """Enhanced HTTP request node.

    Supports:
    - Authentication
    - Retry logic
    - Timeout configuration
    - Response parsing
    - Error handling
    """

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id
        self.method = self._get_method()
        self.url_template = self._get_url_template()
        self.headers = self._get_headers()
        self.auth_config = self._get_auth_config()
        self.retry_config = self._get_retry_config()
        self.timeout = self._get_timeout()

    def _get_method(self) -> str:
        """Extract HTTP method from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        method = config.get("method", "GET")
        return str(method).upper() if method is not None else "GET"

    def _get_url_template(self) -> str:
        """Extract URL template from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        url_template = config.get("url_template", "")
        return str(url_template) if url_template is not None else ""
        return config.get("url", "")

    def _get_headers(self) -> Dict[str, str]:
        """Extract headers from node configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        headers = config.get("headers", {})
        return headers if isinstance(headers, dict) else {}

    def _get_auth_config(self) -> Dict[str, Any]:
        """Extract authentication configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        auth_config = config.get("auth", {})
        return auth_config if isinstance(auth_config, dict) else {}

    def _get_retry_config(self) -> Dict[str, Any]:
        """Extract retry configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        retry_config = config.get("retry", {})
        return retry_config if isinstance(retry_config, dict) else {}
        return {
            "max_retries": config.get("max_retries", 3),
            "retry_delay": config.get("retry_delay", 1.0),
            "retry_on": config.get("retry_on", [500, 502, 503, 504]),
        }

    def _get_timeout(self) -> float:
        """Extract timeout configuration."""
        data = self.node.data or {}
        config = data.get("config", {})
        timeout = config.get("timeout", 30.0)
        return float(timeout) if timeout is not None else 30.0

    def _substitute_url(self, template: str, state: GraphState) -> str:
        """Substitute URL template variables."""
        context = state.get("context", {})
        result = template

        for key, value in context.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))

        return result

    async def _make_request(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        data: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request with retry logic."""
        import aiohttp

        retry_config = self.retry_config
        max_retries = retry_config["max_retries"]
        retry_delay = retry_config["retry_delay"]
        retry_on = retry_config["retry_on"]

        for attempt in range(max_retries + 1):
            try:
                timeout = aiohttp.ClientTimeout(total=self.timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=data if isinstance(data, dict) else None,
                        data=data if not isinstance(data, dict) else None,
                    ) as response:
                        response_data = await response.text()

                        # Try to parse as JSON
                        try:
                            import json

                            response_data = json.loads(response_data)
                        except (json.JSONDecodeError, TypeError):
                            pass

                        if response.status in retry_on and attempt < max_retries:
                            logger.warning(
                                f"[HttpRequestNodeExecutor] Request failed with status {response.status}, "
                                f"retrying ({attempt + 1}/{max_retries})"
                            )
                            await asyncio.sleep(retry_delay)
                            continue

                        return {
                            "status": response.status,
                            "headers": dict(response.headers),
                            "data": response_data,
                            "success": 200 <= response.status < 300,
                        }
            except asyncio.TimeoutError:
                if attempt < max_retries:
                    logger.warning(f"[HttpRequestNodeExecutor] Request timeout, retrying ({attempt + 1}/{max_retries})")
                    await asyncio.sleep(retry_delay)
                    continue
                raise
            except Exception as e:
                if attempt < max_retries:
                    logger.warning(
                        f"[HttpRequestNodeExecutor] Request error: {e}, retrying ({attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(retry_delay)
                    continue
                raise

        # Should not reach here, but just in case
        return {"status": 500, "data": "Max retries exceeded", "success": False}

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute HTTP request node."""
        start_time = time.time()
        logger.info(
            f"[HttpRequestNodeExecutor] >>> Executing HTTP request node '{self.node_id}' | "
            f"method={self.method} | url={self.url_template[:50]}..."
        )

        try:
            # Substitute URL template
            url = self._substitute_url(self.url_template, state)

            # Prepare headers
            headers = self.headers.copy()

            # Add authentication if configured
            auth_config = self.auth_config
            if auth_config.get("type") == "bearer":
                token = auth_config.get("token", "")
                headers["Authorization"] = f"Bearer {token}"
            elif auth_config.get("type") == "basic":
                import base64

                username = auth_config.get("username", "")
                password = auth_config.get("password", "")
                credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
                headers["Authorization"] = f"Basic {credentials}"

            # Get request body from context if POST/PUT/PATCH
            request_data = None
            if self.method in ["POST", "PUT", "PATCH"]:
                context = state.get("context", {})
                request_data = context.get("request_body") or context.get("body")

            # Make request
            result = await self._make_request(url, self.method, headers, request_data)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[HttpRequestNodeExecutor] <<< HTTP request completed | "
                f"node_id={self.node_id} | status={result.get('status')} | "
                f"elapsed={elapsed_ms:.2f}ms"
            )

            response_message = (
                f"HTTP {self.method} {url}: Status {result.get('status')}\nResponse: {str(result.get('data'))[:200]}"
            )

            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=response_message)],
                "context": {"http_response": result},
            }
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[HttpRequestNodeExecutor] !!! Error in HTTP request | "
                f"node_id={self.node_id} | elapsed={elapsed_ms:.2f}ms | "
                f"error={type(e).__name__}: {e}"
            )
            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=f"HTTP request error: {str(e)}")],
            }


class CodeAgentNodeExecutor:
    """
    Executor for CodeAgent nodes in the graph.

    Wraps the CodeAgent module for executing Python code through the
    Thought → Code → Observation iterative pattern.

    Supports two modes:
    - autonomous: Self-planning agent that iterates until completion
    - tool_executor: Simple code execution as a passive tool

    Supports three executor types:
    - local: Secure AST-based Python interpreter
    - docker: Docker sandbox for unrestricted code
    - auto: Smart routing based on code analysis
    """

    def __init__(
        self,
        node: GraphNode,
        node_id: str,
        *,
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[str] = None,
        checkpointer: Optional[Any] = None,
        resolved_model: Optional[Any] = None,
        builder: Optional[Any] = None,
    ):
        self.node = node
        self.node_id = node_id
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.user_id = user_id
        self.checkpointer = checkpointer
        self.resolved_model = resolved_model
        self.builder = builder

        # Parse configuration
        data = node.data or {}
        self.config = data.get("config", {})

        self.executor_type = self.config.get("executor_type", "local")
        self.agent_mode = self.config.get("agent_mode", "autonomous")
        self.max_steps = self.config.get("max_steps", 20)
        self.enable_planning = self.config.get("enable_planning", False)
        self.enable_data_analysis = self.config.get("enable_data_analysis", True)
        self.additional_imports = self.config.get("additional_imports", [])
        self.docker_image = self.config.get("docker_image", "python:3.11-slim")

        self._code_agent = None
        self._agent_lock = asyncio.Lock()

        logger.info(
            f"[CodeAgentNodeExecutor] Initialized | node_id={node_id} | "
            f"executor_type={self.executor_type} | agent_mode={self.agent_mode} | "
            f"max_steps={self.max_steps}"
        )

    def _create_llm_function(self):
        """Create an LLM call function for the CodeAgent."""

        async def llm_call(prompt: str) -> str:
            from langchain_core.messages import HumanMessage

            # Get or create LLM
            if self.resolved_model:
                llm = self.resolved_model
            else:
                from app.core.agent.sample_agent import get_default_model

                llm = get_default_model(
                    llm_model=self.llm_model,
                    api_key=self.api_key,
                    base_url=self.base_url,
                    max_tokens=self.max_tokens,
                )

            # Call LLM
            response = await llm.ainvoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)
            if isinstance(content, list):
                return " ".join(str(item) for item in content)
            return str(content)

        return llm_call

    async def _ensure_code_agent(self):
        """Lazily create the CodeAgent instance."""
        if self._code_agent is not None:
            return self._code_agent

        async with self._agent_lock:
            if self._code_agent is not None:
                return self._code_agent

            try:
                from app.core.agent.code_agent import (
                    CodeAgent,
                    DockerPythonExecutor,
                    ExecutorRouter,
                    LocalPythonExecutor,
                    LoopConfig,
                )

                # Create LLM function
                llm_func = self._create_llm_function()

                # Create executor based on type
                if self.executor_type == "docker":
                    executor = DockerPythonExecutor(
                        image=self.docker_image,
                    )
                elif self.executor_type == "auto":
                    # ExecutorRouter needs local and docker executors
                    local_executor = LocalPythonExecutor(
                        enable_data_analysis=self.enable_data_analysis,
                        additional_authorized_imports=self.additional_imports,
                    )
                    docker_executor = DockerPythonExecutor(
                        image=self.docker_image,
                    )
                    executor = ExecutorRouter(
                        local=local_executor,
                        docker=docker_executor,
                        allow_dangerous=True,  # Route dangerous code to Docker
                    )
                else:  # local
                    executor = LocalPythonExecutor(
                        enable_data_analysis=self.enable_data_analysis,
                        additional_authorized_imports=self.additional_imports,
                    )

                # Create loop config
                loop_config = LoopConfig(
                    max_steps=self.max_steps,
                    enable_planning=self.enable_planning,
                    max_observation_length=10000,
                )

                # Resolve tools for this node
                node_tools = await resolve_tools_for_node(self.node, user_id=self.user_id)
                tools_dict = {}
                if node_tools:
                    for tool in node_tools:
                        if hasattr(tool, "name"):
                            tools_dict[tool.name] = tool
                        elif hasattr(tool, "__name__"):
                            tools_dict[tool.__name__] = tool

                # Create CodeAgent
                self._code_agent = CodeAgent(
                    llm=llm_func,
                    tools=tools_dict if tools_dict else None,
                    executor=executor,
                    config=loop_config,
                    name=f"CodeAgent_{self.node_id}",
                    description=self.config.get("description", ""),
                    enable_data_analysis=self.enable_data_analysis,
                    additional_authorized_imports=self.additional_imports,
                )

                logger.info(
                    f"[CodeAgentNodeExecutor] CodeAgent created | node_id={self.node_id} | "
                    f"tools_count={len(tools_dict)}"
                )

                return self._code_agent

            except ImportError as e:
                logger.error(f"[CodeAgentNodeExecutor] Failed to import CodeAgent: {e}")
                raise RuntimeError(f"CodeAgent module not available: {e}")

    async def _execute_as_tool(self, task: str) -> tuple[str, list[dict]]:
        """Execute code task in tool_executor mode (simple, single execution).

        Returns:
            Tuple of (result, events) where events is a list of CodeAgent step events.
        """
        code_agent = await self._ensure_code_agent()

        # For tool mode, we run with a simpler prompt
        tool_task = f"Execute the following task and return the result directly:\n\n{task}"

        events = []
        result = None

        try:
            async for event in code_agent.run_stream(tool_task):
                # Collect all events for streaming to frontend
                event_dict = {
                    "type": event.event_type,
                    "content": event.content,
                    "step": event.step_number,
                    "metadata": event.metadata or {},
                }
                events.append(event_dict)

                logger.debug(f"[CodeAgentNodeExecutor] Tool event | type={event.event_type} | step={event.step_number}")

                if event.event_type == "final_answer":
                    result = event.content

            result_str = str(result) if result is not None else "Execution completed successfully."
            return result_str, events
        except Exception as e:
            events.append(
                {
                    "type": "error",
                    "content": f"Code execution error: {str(e)}",
                    "step": 0,
                    "metadata": {},
                }
            )
            return f"Code execution error: {str(e)}", events

    async def _execute_as_agent(self, task: str) -> tuple[str, list[dict]]:
        """Execute task in autonomous agent mode with full reasoning loop.

        Returns:
            Tuple of (result, events) where events is a list of CodeAgent step events.
        """
        code_agent = await self._ensure_code_agent()

        events = []
        result = None

        try:
            async for event in code_agent.run_stream(task):
                # Collect all events for streaming to frontend
                event_dict = {
                    "type": event.event_type,
                    "content": event.content,
                    "step": event.step_number,
                    "metadata": event.metadata or {},
                }
                events.append(event_dict)

                logger.debug(
                    f"[CodeAgentNodeExecutor] Agent event | type={event.event_type} | "
                    f"step={event.step_number} | content_preview={str(event.content)[:100]}..."
                )

                if event.event_type == "final_answer":
                    result = event.content

            result_str = str(result) if result is not None else "Task completed."
            return result_str, events
        except Exception as e:
            logger.error(f"[CodeAgentNodeExecutor] Agent execution error: {e}")
            events.append(
                {
                    "type": "error",
                    "content": f"Agent execution error: {str(e)}",
                    "step": 0,
                    "metadata": {},
                }
            )
            return f"Agent execution error: {str(e)}", events

    def _extract_task_from_state(self, state: GraphState) -> str:
        """Extract the task/query from the graph state."""
        messages = cast(list, state.get("messages", []))
        context = state.get("context", {})

        # Priority 1: Check for explicit code_task in context
        if "code_task" in context:
            return str(context["code_task"])

        # Priority 2: Check for task in context
        if "task" in context:
            return str(context["task"])

        # Priority 3: Use the last human message
        if messages:
            for msg in reversed(messages):
                if hasattr(msg, "type") and msg.type == "human":
                    content = msg.content
                    return (
                        str(content)
                        if isinstance(content, (str, list))
                        else (content[0] if isinstance(content, list) and content else str(content))
                    )  # type: ignore[return-value]
                if hasattr(msg, "content") and not hasattr(msg, "type"):
                    # Fallback to last message content
                    content = msg.content
                    return (
                        str(content)
                        if isinstance(content, (str, list))
                        else (content[0] if isinstance(content, list) and content else str(content))
                    )  # type: ignore[return-value]

        # Priority 4: Fallback
        return "Analyze the current context and provide a helpful response."

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute the CodeAgent node.

        Returns state updates including:
        - messages: The final response message
        - context: Execution metadata including code_agent_events for streaming
        - code_agent_events: List of step events for frontend process tracking
        """
        start_time = time.time()

        logger.info(
            f"[CodeAgentNodeExecutor] >>> Executing node '{self.node_id}' | "
            f"mode={self.agent_mode} | executor={self.executor_type}"
        )

        try:
            # Extract task from state
            task = self._extract_task_from_state(state)

            # Execute based on mode - now returns (result, events)
            if self.agent_mode == "tool_executor":
                result, events = await self._execute_as_tool(task)
            else:
                result, events = await self._execute_as_agent(task)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(
                f"[CodeAgentNodeExecutor] <<< Node '{self.node_id}' completed | "
                f"elapsed={elapsed_ms:.2f}ms | result_length={len(str(result))} | "
                f"events_count={len(events)}"
            )

            # Create response message
            response_message = AIMessage(content=result)

            return {
                "current_node": self.node_id,
                "messages": [response_message],
                "context": {
                    "code_agent_result": result,
                    "code_agent_mode": self.agent_mode,
                    "code_agent_executor": self.executor_type,
                },
                # Include events for StreamEventHandler to process
                "code_agent_events": events,
            }

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                f"[CodeAgentNodeExecutor] !!! Error in node '{self.node_id}' | "
                f"elapsed={elapsed_ms:.2f}ms | error={type(e).__name__}: {e}"
            )

            error_message = f"CodeAgent error: {str(e)}"
            return {
                "current_node": self.node_id,
                "messages": [AIMessage(content=error_message)],
                "context": {"code_agent_error": str(e)},
                "code_agent_events": [
                    {
                        "type": "error",
                        "content": str(e),
                        "step": 0,
                        "metadata": {},
                    }
                ],
            }
