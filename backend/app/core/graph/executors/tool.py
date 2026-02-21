"""
Tool Executors - Executors for tool invocation and custom function nodes.
"""

import time
from typing import Any, Dict

from langchain_core.messages import AIMessage
from loguru import logger

try:
    from langgraph.types import Command

    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None  # type: ignore[assignment,misc]

from app.core.graph.executors.agent import apply_node_output_mapping
from app.core.graph.expression_evaluator import StateWrapper
from app.core.graph.graph_state import GraphState
from app.models.graph import GraphNode


class ToolNodeExecutor:
    """Executor for a Tool node in the graph.

    Executes a specific tool selected in the node configuration.
    Supports input mapping from state variables to tool arguments.
    """

    STATE_READS: tuple = ("messages", "context", "*")
    STATE_WRITES: tuple = ("messages", "current_node")

    def __init__(self, node: GraphNode, node_id: str, user_id: str = None):
        self.node = node
        self.node_id = node_id
        self.user_id = user_id

        data = self.node.data or {}
        self.config = data.get("config", {})
        self.tool_name = self.config.get("toolName")
        self.input_mapping = self.config.get("inputMapping", [])

    async def _get_tool_function(self):
        """Resolve the actual tool function."""
        # This is a simplified resolution. In a real system, we'd use a tool registry
        # similar to how the agent resolves tools.
        # For now, we'll assume standard tools are available via a helper.
        # We need a way to get the actual callable.
        # Re-using the tool resolution logic from agent/node_tools.py might be best
        from app.core.agent.node_tools import resolve_tools_for_node

        # Tools resolved for node are a list of LangChain tools or structured tools
        tools = await resolve_tools_for_node(self.node, user_id=self.user_id)

        target_tool = None

        def _normalize_name(name: Any) -> str:
            return str(name).strip().lower() if name else ""

        normalized_name = _normalize_name(self.tool_name)

        if not tools:
            # Fallback: try to find it in the global registry if not explicitly linked?
            # But usually tools must be linked to the node.
            pass

        if isinstance(tools, list):
            for tool in tools:
                if _normalize_name(tool.name) == normalized_name:
                    target_tool = tool
                    break

        return target_tool

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute the tool."""
        start_time = time.time()
        logger.info(f"[ToolNodeExecutor] >>> Executing tool '{self.tool_name}' for node '{self.node_id}'")

        if not self.tool_name:
            logger.error(f"[ToolNodeExecutor] No tool name configured for node {self.node_id}")
            return {"messages": [AIMessage(content="Error: No tool selected.")]}

        try:
            tool = await self._get_tool_function()
            if not tool:
                raise ValueError(f"Tool '{self.tool_name}' not found or not available for this node.")

            # Prepare arguments from input mapping
            tool_args = {}
            state_wrapper = StateWrapper(dict(state))

            # Resolve arguments
            for mapping in self.input_mapping:
                param_name = mapping.get("key")
                source_type = mapping.get("type", "static")  # static or variable
                source_value = mapping.get("value")

                if not param_name:
                    continue

                if source_type == "variable":
                    # Fetch from state
                    # Simple support for 'message.content' or 'context.foo'
                    val = self._get_value_by_path(state_wrapper, source_value)
                    tool_args[param_name] = val
                else:
                    # Static value
                    tool_args[param_name] = source_value

            logger.info(f"[ToolNodeExecutor] Invoking tool with args: {tool_args}")

            # Invoke the tool
            # LangChain tools usually support .invoke(args) or .ainvoke(args)
            if hasattr(tool, "ainvoke"):
                result = await tool.ainvoke(tool_args)
            else:
                result = tool.invoke(tool_args)

            # Result is usually a string or artifact.
            # We wrap it in a ToolMessage if it's not one, or just an AIMessage?
            # Creating a ToolMessage requires a tool_call_id which we might not have if not triggered by an LLM.
            # So we represent it as a generic message or structured output.

            # For pure tool nodes, we often want the result to be available in state,
            # not necessarily just appended to messages.

            output_content = str(result)

            return_dict = {
                "messages": [AIMessage(content=f"Tool '{self.tool_name}' output: {output_content}")],
                "current_node": self.node_id,
            }

            # Apply output mapping (save tool result to state)
            # We wrap result to allow 'result' or 'result.foo' access
            apply_node_output_mapping(self.config, result, return_dict, self.node_id)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"[ToolNodeExecutor] <<< Tool complete | elapsed={elapsed_ms:.2f}ms")

            return return_dict

        except Exception as e:
            logger.error(f"[ToolNodeExecutor] Error executing tool: {e}")
            return {"messages": [AIMessage(content=f"Error executing tool '{self.tool_name}': {str(e)}")]}

    def _get_value_by_path(self, obj: Any, path: str) -> Any:
        """Helper to get value from state."""
        # Reuse logic from Loop/Logic modules or create shared util?
        # For now, quick dup to keep modules independent or move to expression_evaluator.
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


class FunctionNodeExecutor:
    """Executor for a Function node in the graph.

    Executes a predefined function (math, string, etc.) or custom Python code segment.
    """

    STATE_READS: tuple = ("*",)
    STATE_WRITES: tuple = "*"  # Can write to any via output mapping

    def __init__(self, node: GraphNode, node_id: str):
        self.node = node
        self.node_id = node_id

        data = self.node.data or {}
        self.config = data.get("config", {})
        self.execution_mode = self.config.get("execution_mode", "predefined")
        self.function_name = self.config.get("function_name")
        self.function_code = self.config.get("function_code")

        # Predefined functions registry
        self.PREDEFINED_FUNCTIONS = {
            "math_add": lambda a, b: float(a) + float(b),
            "math_multiply": lambda a, b: float(a) * float(b),
            "string_concat": lambda a, b: str(a) + str(b),
            "dict_get": lambda d, k: d.get(k) if isinstance(d, dict) else None,
            "dict_set": self._dict_set,
        }

    def _dict_set(self, d, k, v):
        if not isinstance(d, dict):
            return {}
        new_d = d.copy()
        new_d[k] = v
        return new_d

    async def __call__(self, state: GraphState) -> Dict[str, Any]:
        """Execute the function."""
        logger.info(f"[FunctionNodeExecutor] >>> Executing function '{self.execution_mode}' | node_id={self.node_id}")

        result = None

        try:
            if self.execution_mode == "custom":
                # Execute custom python code
                if not self.function_code:
                    raise ValueError("No custom code provided")

                # Sandbox execution similar to condition evaluator
                # BUT: Code execution is dangerous.
                # Ideally we restrict this heavily or use a proper sandbox.
                # For this implementation, we use the same restrictive eval/exec as condition,
                # but maybe slightly more permissive to allow logic?
                # Using 'exec' allows statements, 'eval' only expressions.
                # The prompt says 'Use "result" variable for output' -> implies exec.

                # Using StateWrapper for easier access
                wrapped_state = StateWrapper(dict(state))

                # Local scope for execution
                local_scope = {
                    "state": wrapped_state,
                    "context": state.get("context", {}),
                    "messages": state.get("messages", []),
                    "result": None,  # Output variable
                }

                # We need to trust the user here or sandbox strictly.
                # For now, we execute with limited builtins.
                exec(self.function_code, {"__builtins__": {}}, local_scope)

                result = local_scope.get("result")

            else:
                # Predefined function
                if not self.function_name:
                    raise ValueError("No predefined function selected")

                func = self.PREDEFINED_FUNCTIONS.get(self.function_name)
                if not func:
                    raise ValueError(f"Unknown predefined function: {self.function_name}")

                # Helper to get args from config (assume config has args map?)
                # For simplicity, let's assume 'args' in config maps param names to values/variables
                _args_config = self.config.get("args", {})
                # Or just use the input_mapping logic?
                # The schema for predefined functions usually needs specific inputs.
                # Let's assume generic input names 'arg1', 'arg2' for now or from config.

                # Resolving arguments... simplified for this example
                # In a real app, the UI would provide fields for 'a' and 'b' for 'math_add'.
                arg1 = self.config.get("arg1")
                arg2 = self.config.get("arg2")

                result = func(arg1, arg2)

            return_dict = {"current_node": self.node_id}

            # Map result to state
            apply_node_output_mapping(self.config, result, return_dict, self.node_id)

            return return_dict

        except Exception as e:
            logger.error(f"[FunctionNodeExecutor] Error: {e}")
            return {"messages": [AIMessage(content=f"Function error: {e}")]}
