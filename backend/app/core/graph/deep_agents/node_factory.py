"""Node builder for DeepAgents graph builder.

Builds different types of nodes (root, manager, worker, code_agent).
"""

from typing import TYPE_CHECKING, Any, Optional

from deepagents import CompiledSubAgent
from langchain_core.messages import AIMessage
from loguru import logger

if TYPE_CHECKING:
    from app.models.graph import GraphNode

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

    def _should_use_shared_backend(self, config: CodeAgentConfig) -> bool:
        """Check if shared backend should be used."""
        shared_backend = self.builder.get_shared_backend()
        return (
            shared_backend
            and not self.builder.is_shared_backend_creation_failed()
            and config.executor_type in ("docker", "auto")
        )

    def _build_code_agent_executor(self, config: CodeAgentConfig) -> Any:
        """Build executor for CodeAgent based on config."""
        from app.core.agent.code_agent import DockerPythonExecutor, ExecutorRouter
        from app.core.agent.code_agent.executor.backend_executor import BackendPythonExecutor

        if self._should_use_shared_backend(config):
            from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

            shared_backend = self.builder.get_shared_backend()

            if isinstance(shared_backend, PydanticSandboxAdapter):
                shared_executor = BackendPythonExecutor(backend=shared_backend)
                logger.info(f"{LOG_PREFIX} CodeAgent '{config.name}' using shared Docker backend")

                if config.executor_type == "docker":
                    return shared_executor
                else:
                    return ExecutorRouter(
                        local=self._create_local_executor(config),
                        docker=shared_executor,
                        allow_dangerous=True,
                    )

        if config.executor_type == "docker":
            return DockerPythonExecutor(image=config.docker_image)
        elif config.executor_type == "auto":
            return ExecutorRouter(
                local=self._create_local_executor(config),
                docker=DockerPythonExecutor(image=config.docker_image),
                allow_dangerous=True,
            )
        else:
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
