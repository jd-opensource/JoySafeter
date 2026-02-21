"""
Agent Executors - Executors for AI agent nodes.
"""
import asyncio
import time
from typing import Any, Dict, List, Optional, Sequence, Union, cast

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import Runnable, RunnableConfig
from loguru import logger

try:
    from langgraph.types import Command
    COMMAND_AVAILABLE = True
except ImportError:
    COMMAND_AVAILABLE = False
    Command = None  # type: ignore[assignment,misc]
    logger.warning("[AgentExecutors] langgraph.types.Command not available, Command mode disabled")

from app.core.agent.node_tools import resolve_tools_for_node
from app.core.agent.sample_agent import get_agent
from app.core.graph.graph_state import GraphState
from app.models.graph import GraphNode


class BaseLLMNodeExecutor:
    """Base class for LLM-backed node executors.

    Provides shared constructor parameters and initialization for
    AgentNodeExecutor and CodeAgentNodeExecutor.
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
    raw_payload = result.dict() if hasattr(result, "dict") else (
        result if isinstance(result, dict) else {"value": result}
    )
    return_dict["node_outputs"] = {node_id: raw_payload}

    if not output_mapping:
        return

    logger.debug(f"[NodeExecutor] Applying output mapping for node '{node_id}': {output_mapping}")

    # Helper to safely get value from nested dicts
    def get_value(obj: Any, path: str) -> Any:
        if path == "result":
            return obj
        
        parts = path.split(".")
        current = obj
        
        # If path starts with "result.", skip the first part
        if parts[0] == "result":
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

    for state_key, result_path in output_mapping.items():
        try:
            # Extract value
            value = get_value(result, result_path)
            
            if value is not None:
                return_dict[state_key] = value
                logger.debug(f"[NodeExecutor] Mapped {result_path} -> {state_key} = {str(value)[:50]}...")
        except Exception as e:
            logger.warning(
                f"[NodeExecutor] Failed to map output {result_path} -> {state_key} for node '{node_id}': {e}"
            )


class AgentNodeExecutor(BaseLLMNodeExecutor):
    """
    Executor for an Agent node in the graph.

    Wraps a LangChain `create_agent` graph (tools + middleware) using the same
    implementation approach as `app.core.agent.sample_agent.get_agent`.
    """

    STATE_READS: tuple = ("messages", "context")
    STATE_WRITES: tuple = ("messages", "current_node")

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
        super().__init__(
            node, node_id,
            llm_model=llm_model, api_key=api_key, base_url=base_url,
            max_tokens=max_tokens, user_id=user_id, checkpointer=checkpointer,
            resolved_model=resolved_model, builder=builder,
        )
        self.system_prompt = self._get_system_prompt()
        self.messages_window = messages_window

        self._agent: Runnable | None = None
        self._agent_lock = asyncio.Lock()

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


    async def __call__(self, state: GraphState, config: Optional[RunnableConfig] = None) -> Union[Dict[str, Any], Command]:
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
        node_config = data.get("config", {})  # Renamed to node_config to avoid conflict
        use_command_mode = node_config.get("useCommandMode", False) and COMMAND_AVAILABLE

        logger.info(
            f"[AgentNodeExecutor] >>> Executing node '{self.node_id}' | "
            f"input_messages_count={len(messages)} | command_mode={use_command_mode}"
        )

        input_messages = messages[-self.messages_window :] if self.messages_window > 0 else messages

        try:
            agent = await self._ensure_agent()

            result = await agent.ainvoke(
                {"messages": input_messages},
                config=config,
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

            # Apply output mapping if configured
            apply_node_output_mapping(config, result, return_dict, self.node_id)

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
class CodeAgentNodeExecutor(BaseLLMNodeExecutor):
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
        super().__init__(
            node, node_id,
            llm_model=llm_model, api_key=api_key, base_url=base_url,
            max_tokens=max_tokens, user_id=user_id, checkpointer=checkpointer,
            resolved_model=resolved_model, builder=builder,
        )

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

    async def _execute_stream(self, task: str) -> tuple[str, list[dict]]:
        """Execute a task via CodeAgent's streaming interface.

        Collects all events and extracts the final answer.

        Returns:
            Tuple of (result, events) where events is a list of CodeAgent step events.
        """
        code_agent = await self._ensure_code_agent()

        events = []
        result = None

        try:
            async for event in code_agent.run_stream(task):
                event_dict = {
                    "type": event.event_type,
                    "content": event.content,
                    "step": event.step_number,
                    "metadata": event.metadata or {},
                }
                events.append(event_dict)

                logger.debug(
                    f"[CodeAgentNodeExecutor] Event | type={event.event_type} | "
                    f"step={event.step_number} | content_preview={str(event.content)[:100]}..."
                )

                if event.event_type == "final_answer":
                    result = event.content

            result_str = str(result) if result is not None else "Task completed."
            return result_str, events
        except Exception as e:
            logger.error(f"[CodeAgentNodeExecutor] Execution error: {e}")
            events.append(
                {
                    "type": "error",
                    "content": f"Execution error: {str(e)}",
                    "step": 0,
                    "metadata": {},
                }
            )
            return f"Execution error: {str(e)}", events

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

            # Prepare task — tool_executor mode uses a simpler directive prompt
            if self.agent_mode == "tool_executor":
                task = f"Execute the following task and return the result directly:\n\n{task}"

            result, events = await self._execute_stream(task)

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
