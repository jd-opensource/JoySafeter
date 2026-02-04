"""Node builder for DeepAgents graph builder.

Builds different types of nodes (root, manager, worker, code_agent, a2a_agent).
"""

from typing import TYPE_CHECKING, Any, Optional

from deepagents import CompiledSubAgent
from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable, RunnableLambda
from loguru import logger

if TYPE_CHECKING:
    from app.models.graph import GraphNode

from app.core.a2a.client import resolve_a2a_url, send_message
from app.core.graph.deep_agents.node_config import AgentConfig, CodeAgentConfig

LOG_PREFIX = "[NodeBuilder]"


class DeepAgentsNodeBuilder:
    """Builds nodes for DeepAgents graph."""

    def __init__(
        self,
        builder: Any,  # DeepAgentsGraphBuilder instance
    ):
        """Initialize node builder."""
        self.builder = builder
        self._node_id_to_name = builder.get_node_id_to_name()

    def _create_deep_agent_from_config(
        self, config: AgentConfig, name: str, subagents: Optional[list[Any]] = None, is_root: bool = False
    ) -> Any:
        """Create DeepAgent from config - unified method for root and manager."""
        return self.builder._create_deep_agent(
            model=config.model,
            system_prompt=config.system_prompt,
            tools=config.tools,
            subagents=subagents or [],
            middleware=config.middleware,
            name=name,
            is_root=is_root,
            skills=config.skills,
            backend=config.backend,
        )

    async def build_root_node(self, node: "GraphNode", node_name: str) -> Any:
        """Build root node as DeepAgent using unified config."""
        logger.info(f"{LOG_PREFIX} Building root DeepAgent: '{node_name}'")
        config = await AgentConfig.from_node(node, self.builder, self._node_id_to_name)
        return self._create_deep_agent_from_config(config, node_name, is_root=True)

    async def build_manager_node(
        self,
        node: "GraphNode",
        node_name: str,
        subagents: list[Any],
        is_root: bool = False,
    ) -> Any:
        """Build Manager (DeepAgent) with pre-built CompiledSubAgent subagents using unified config."""
        logger.info(f"{LOG_PREFIX} Building manager: '{node_name}' with {len(subagents)} subagents")
        config = await AgentConfig.from_node(node, self.builder, self._node_id_to_name)
        deep_agent = self._create_deep_agent_from_config(config, node_name, subagents, is_root)
        return deep_agent.with_config(
            {"metadata": {"node_id": node.id, "node_label": config.label, "current_agent_name": node_name}}
        )

    async def build_worker_node(self, node: "GraphNode") -> Any:
        """Build worker node using unified config."""
        config = await AgentConfig.from_node(node, self.builder, self._node_id_to_name, default_description=None)

        if not config.description:
            config.description = f"Specialized worker: {config.label or config.name}"

        if config.node_type == "code_agent":
            return await self.build_code_agent_node(node)

        if config.node_type == "a2a_agent":
            return await self.build_a2a_agent_node(node)

        logger.info(f"{LOG_PREFIX} Building worker: '{config.name}'")

        from langchain.agents import create_agent

        agent_runnable: Any = create_agent(
            model=config.model,
            tools=config.tools,
            system_prompt=config.system_prompt,
            middleware=config.middleware,
        )

        return CompiledSubAgent(
            name=config.name,
            description=config.description or "",
            runnable=agent_runnable,
        )

    def _create_local_executor(self, config: CodeAgentConfig) -> Any:
        """Create LocalPythonExecutor with config."""
        from app.core.agent.code_agent import LocalPythonExecutor

        return LocalPythonExecutor(
            enable_data_analysis=config.enable_data_analysis,
            additional_authorized_imports=config.additional_imports,
        )

    def _build_code_agent_executor(self, config: CodeAgentConfig) -> Any:
        """Build executor for CodeAgent - uses shared backend if available."""
        from app.core.agent.code_agent import ExecutorRouter
        from app.core.agent.code_agent.executor.backend_executor import BackendPythonExecutor

        backend = self.builder.get_backend()

        # Use shared backend if available and executor type supports Docker
        if backend and config.executor_type in ("docker", "auto"):
            from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

            if isinstance(backend, PydanticSandboxAdapter):
                docker_executor = BackendPythonExecutor(backend=backend)
                logger.info(f"{LOG_PREFIX} CodeAgent '{config.name}' using shared Docker backend")

                if config.executor_type == "docker":
                    return docker_executor
                else:  # auto
                    return ExecutorRouter(
                        local=self._create_local_executor(config),
                        docker=docker_executor,
                        allow_dangerous=True,
                    )

        # Fall back to local executor
        if config.executor_type in ("docker", "auto") and not backend:
            logger.debug(
                f"{LOG_PREFIX} CodeAgent '{config.name}' requested {config.executor_type} "
                "but no shared Docker backend, using local executor"
            )
        return self._create_local_executor(config)

    def _build_code_agent_tools_dict(self, tools: list[Any]) -> dict[str, Any]:
        """Convert tools list to dict for CodeAgent."""
        return {
            tool.name if hasattr(tool, "name") else tool.__name__: tool
            for tool in tools
            if hasattr(tool, "name") or hasattr(tool, "__name__")
        }

    def _create_llm_call_wrapper(self, model: Any) -> Any:
        """Create LLM call wrapper for CodeAgent."""
        from langchain_core.messages import HumanMessage

        async def llm_call(prompt: str) -> str:
            response = await model.ainvoke([HumanMessage(content=prompt)])
            content = response.content if hasattr(response, "content") else str(response)
            if isinstance(content, list):
                return " ".join(str(item) for item in content)
            return str(content)

        return llm_call

    def _create_code_agent_runnable(self, config: CodeAgentConfig, code_agent: Any) -> Any:
        """Create runnable wrapper for CodeAgent."""
        from langchain_core.runnables import RunnableLambda

        async def code_agent_invoke(inputs: dict) -> dict:
            # Extract task from inputs - support both dict and BaseMessage formats
            task = inputs.get("task")
            if not task:
                messages = inputs.get("messages", [])
                if messages:
                    last_msg = messages[-1]
                    # Handle LangChain BaseMessage objects (HumanMessage, AIMessage, etc.)
                    if hasattr(last_msg, "content"):
                        task = last_msg.content
                    # Handle dict format (fallback)
                    elif isinstance(last_msg, dict):
                        task = last_msg.get("content", "")
                    else:
                        task = str(last_msg) if last_msg else ""
                else:
                    task = ""

            if config.agent_mode == "tool_executor":
                result = await code_agent.run(f"Execute the following task and return the result directly:\n\n{task}")
            else:
                result = await code_agent.run(task)

            # Return AIMessage object instead of dict to match DeepAgents format
            # DeepAgents expects BaseMessage objects with .text attribute
            return {
                "messages": [AIMessage(content=str(result) if result else "Task completed.")],
                "result": result,
            }

        return RunnableLambda(code_agent_invoke)

    async def build_code_agent_node(self, node: "GraphNode") -> Any:
        """Build CodeAgent as SubAgent using unified CodeAgentConfig."""
        config = await CodeAgentConfig.from_node(node, self.builder, self._node_id_to_name)

        logger.info(
            f"{LOG_PREFIX} Building CodeAgent SubAgent: '{config.name}' | "
            f"mode={config.agent_mode} | executor={config.executor_type}"
        )

        try:
            from app.core.agent.code_agent import CodeAgent, LoopConfig

            executor = self._build_code_agent_executor(config)
            loop_config = LoopConfig(
                max_steps=config.max_steps,
                enable_planning=config.enable_planning,
                max_observation_length=10000,
            )
            llm_call = self._create_llm_call_wrapper(config.model)
            tools_dict = self._build_code_agent_tools_dict(config.tools)

            code_agent = CodeAgent(
                llm=llm_call,
                tools=tools_dict if tools_dict else None,
                executor=executor,
                config=loop_config,
                name=config.name,
                description=config.description or "",
                enable_data_analysis=config.enable_data_analysis,
                additional_authorized_imports=config.additional_imports,
            )

            runnable = self._create_code_agent_runnable(config, code_agent)

            compiled = CompiledSubAgent(
                name=config.name,
                description=config.description or "",
                runnable=runnable,
            )
            logger.info(f"{LOG_PREFIX} Created CodeAgent SubAgent: '{config.name}'")
            return compiled

        except ImportError as e:
            logger.warning(f"{LOG_PREFIX} CodeAgent import failed: {e}, falling back to config")
            return {
                "name": config.name,
                "description": config.description,
                "type": "code_agent",
                "config": config.to_dict(),
            }
        except Exception as e:
            logger.error(f"{LOG_PREFIX} CodeAgent SubAgent creation failed: {e}")
            raise

    async def build_a2a_agent_node(self, node: "GraphNode") -> Any:
        """Build A2A agent as SubAgent: runnable calls remote A2A Server via message/send.

        Production features:
        - Automatic retry with exponential backoff
        - Long-running task polling (tasks/get)
        - Connection pooling
        - Auth headers support
        """
        config = await AgentConfig.from_node(
            node, self.builder, self._node_id_to_name, default_description="Remote A2A agent"
        )

        a2a_url: Optional[str] = config.a2a_url
        auth_headers: Optional[dict[str, str]] = config.a2a_auth_headers

        if not a2a_url and config.agent_card_url:
            try:
                a2a_url = await resolve_a2a_url(config.agent_card_url, auth_headers=auth_headers)
            except Exception as e:
                logger.error(f"{LOG_PREFIX} A2A agent '{config.name}': failed to resolve Agent Card: {e}")
                raise ValueError(f"Invalid agent_card_url for A2A agent: {e}") from e
        if not a2a_url:
            raise ValueError(f"A2A agent '{config.name}' requires config.a2a_url or config.agent_card_url")

        logger.info(
            f"{LOG_PREFIX} Building A2A SubAgent: '{config.name}' -> {a2a_url}",
            extra={"has_auth": bool(auth_headers)},
        )

        # Capture variables for closure
        captured_url = a2a_url
        captured_auth = auth_headers

        async def a2a_invoke(inputs: dict) -> dict:
            task = inputs.get("task")
            if not task:
                messages = inputs.get("messages", [])
                if messages:
                    last_msg = messages[-1]
                    if hasattr(last_msg, "content"):
                        task = last_msg.content
                    elif isinstance(last_msg, dict):
                        task = last_msg.get("content", "")
                    else:
                        task = str(last_msg) if last_msg else ""
                else:
                    task = ""
            task_text = str(task).strip() if task else ""

            result = await send_message(
                captured_url,
                task_text,
                auth_headers=captured_auth,
                wait_for_completion=True,  # Poll for long-running tasks
            )

            if not result.ok:
                content = f"[A2A error] {result.error or 'Unknown error'}"
                logger.warning(
                    f"{LOG_PREFIX} A2A invoke failed",
                    extra={
                        "a2a_url": captured_url,
                        "error": result.error,
                        "duration_ms": result.duration_ms,
                    },
                )
            else:
                content = result.text or ""
                logger.info(
                    f"{LOG_PREFIX} A2A invoke completed",
                    extra={
                        "a2a_url": captured_url,
                        "task_id": result.task_id,
                        "state": result.state,
                        "duration_ms": result.duration_ms,
                        "text_length": len(content),
                    },
                )

            return {
                "messages": [AIMessage(content=content)],
                "result": content,
            }

        runnable: Runnable[dict[str, Any], dict[str, Any]] = RunnableLambda(
            func=lambda x: x,  # dummy sync func, not used
            afunc=a2a_invoke,  # async func is the actual implementation
        )
        return CompiledSubAgent(
            name=config.name,
            description=config.description or "Remote A2A agent",
            runnable=runnable,
        )
