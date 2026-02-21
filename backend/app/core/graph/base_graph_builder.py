"""
Base Graph Builder - Base class with shared utilities.

Provides common functionality for node/edge management, configuration extraction,
and graph structure analysis.
"""

import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set, Type

from langgraph.graph.state import CompiledStateGraph

from app.core.agent.sample_agent import get_default_model
from app.core.graph.node_executors import (
    AgentNodeExecutor,
    AggregatorNodeExecutor,
    CodeAgentNodeExecutor,
    ConditionAgentNodeExecutor,
    ConditionNodeExecutor,
    DirectReplyNodeExecutor,
    FunctionNodeExecutor,
    GetStateNodeExecutor,
    HttpRequestNodeExecutor,
    JSONParserNodeExecutor,
    LoopConditionNodeExecutor,
    RouterNodeExecutor,
    SetStateNodeExecutor,
    ToolNodeExecutor,
)
from app.core.graph.node_type_registry import NodeTypeRegistry
from app.core.model.utils.model_ref import parse_model_ref
from app.core.tools.tool import EnhancedTool
from app.core.tools.tool_registry import get_global_registry
from app.models.graph import AgentGraph, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# ==================== Optional deepagents imports ====================
# DEEPAGENTS_AVAILABLE is defined in base_graph_builder but also needed in other modules
# 先声明为可选，避免在 except 中赋 None 触发 mypy "Cannot assign to a type"
CompiledSubAgent: Type[Any] | None = None
create_deep_agent: Any = None
DEEPAGENTS_AVAILABLE = False

try:
    from deepagents import CompiledSubAgent as _CompiledSubAgent
    from deepagents import create_deep_agent as _create_deep_agent

    CompiledSubAgent = _CompiledSubAgent
    create_deep_agent = _create_deep_agent
    DEEPAGENTS_AVAILABLE = True
except ImportError:
    logger.warning("[GraphBuilder] deepagents not available, DeepAgents mode will be disabled")

# Constants
DEFAULT_RECURSION_LIMIT = 200  # Safer default, can be overridden via graph config


class BaseGraphBuilder(ABC):
    """
    Base class for graph builders with shared utilities.

    Provides common functionality for node/edge management, configuration extraction,
    and graph structure analysis.
    """

    def __init__(
        self,
        graph: AgentGraph,
        nodes: List[GraphNode],
        edges: List[GraphEdge],
        llm_model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 4096,
        user_id: Optional[Any] = None,
        model_service: Optional[Any] = None,
    ):
        self.graph = graph
        self.nodes = nodes
        self.edges = edges
        self.llm_model = llm_model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.user_id = user_id
        # 可选：提供 ModelService，用于根据 model_name 实例化运行时模型
        self.model_service = model_service

        # Build lookup maps
        self._node_map: Dict[uuid.UUID, GraphNode] = {n.id: n for n in nodes}
        self._node_id_to_name: Dict[uuid.UUID, str] = {}

        # Build edge lookups
        self._outgoing_edges: Dict[uuid.UUID, List[uuid.UUID]] = {}
        for edge in edges:
            if edge.source_node_id not in self._outgoing_edges:
                self._outgoing_edges[edge.source_node_id] = []
            self._outgoing_edges[edge.source_node_id].append(edge.target_node_id)

        self._incoming_edges: Dict[uuid.UUID, List[uuid.UUID]] = {}
        for edge in edges:
            if edge.target_node_id not in self._incoming_edges:
                self._incoming_edges[edge.target_node_id] = []
            self._incoming_edges[edge.target_node_id].append(edge.source_node_id)

    # ==================== Node Utilities ====================

    def _get_node_type(self, node: GraphNode) -> str:
        """Get node type, preferring node.data.type over node.type."""
        data = node.data or {}
        node_type = data.get("type") or node.type
        return node_type or "agent"

    def _get_node_name(self, node: GraphNode) -> str:
        """Generate a unique name for a node."""
        data = node.data or {}
        label = data.get("label", "")
        node_type = self._get_node_type(node)

        if label:
            name = str(label).lower().replace(" ", "_").replace("-", "_")
            name = f"{name}_{str(node.id)[:8]}"
        else:
            name = f"{node_type}_{str(node.id)[:8]}"

        return name

    def _get_node_display_name(self, node: GraphNode) -> str:
        """
        Get the display name for a node.

        Priority:
        1. Node label (from data.label)
        2. Generated unique name

        Args:
            node: GraphNode to get name for

        Returns:
            Display name string
        """
        data = node.data or {}
        label = data.get("label", "")

        if label:
            return str(label)

        node_name = self._node_id_to_name.get(node.id) or self._get_node_name(node)
        return str(node_name) if node_name is not None else ""

    def _get_system_prompt_from_node(self, node: GraphNode) -> Optional[str]:
        """Extract system prompt from node configuration."""
        if node.prompt:
            return node.prompt
        data = node.data or {}
        config: Dict[str, Any] = data.get("config", {})
        return config.get("systemPrompt", "") or config.get("prompt", "") or None

    def _get_direct_children(self, node: GraphNode) -> List[GraphNode]:
        """Get direct child nodes (nodes connected via outgoing edges)."""
        child_ids = self._outgoing_edges.get(node.id, [])
        return [self._node_map[child_id] for child_id in child_ids if child_id in self._node_map]

    def _find_start_nodes(self) -> List[GraphNode]:
        """Find nodes that should be connected to START (no incoming edges)."""
        start_nodes = []
        for node in self.nodes:
            if node.id not in self._incoming_edges or len(self._incoming_edges[node.id]) == 0:
                start_nodes.append(node)
        return start_nodes

    def _find_end_nodes(self) -> List[GraphNode]:
        """Find nodes that should be connected to END (no outgoing edges)."""
        end_nodes = []
        for node in self.nodes:
            if node.id not in self._outgoing_edges or len(self._outgoing_edges[node.id]) == 0:
                end_nodes.append(node)
        return end_nodes

    def _is_deep_agents_enabled(self, node: GraphNode) -> bool:
        """Check if DeepAgents mode is enabled for a node."""
        if not DEEPAGENTS_AVAILABLE:
            return False
        data = node.data or {}
        config = data.get("config", {})
        return config.get("useDeepAgents", False) is True

    async def _create_node_executor(self, node: GraphNode, node_name: str) -> Any:
        """Create the appropriate executor based on node type.

        Uses NodeTypeRegistry for centralized type management.
        """
        node_type = self._get_node_type(node)

        # Try to get executor class from registry first
        executor_class = NodeTypeRegistry.get_executor_class(node_type)
        if executor_class:
            # Use registry metadata to create executor
            return await self._create_executor_from_registry(executor_class, node, node_name, node_type)

        # Fallback to manual mapping (for backward compatibility)
        if node_type == "agent":
            return await self._create_llm_executor(AgentNodeExecutor, node, node_name)
        elif node_type == "condition":
            return ConditionNodeExecutor(node, node_name)
        elif node_type == "direct_reply":
            return DirectReplyNodeExecutor(node, node_name)
        elif node_type == "router_node":
            return RouterNodeExecutor(node, node_name)
        elif node_type == "tool_node":
            return ToolNodeExecutor(node, node_name, user_id=self.user_id)
        elif node_type == "function_node":
            return FunctionNodeExecutor(node, node_name)
        elif node_type == "loop_condition_node":
            return LoopConditionNodeExecutor(node, node_name)
        elif node_type == "iteration":
            # Deprecated: legacy node type, use loop_condition_node instead
            logger.warning(
                f"[BaseGraphBuilder] Deprecated node type 'iteration' used, "
                f"mapping to LoopConditionNodeExecutor | node_id={node.id}"
            )
            return LoopConditionNodeExecutor(node, node_name)
        elif node_type == "aggregator_node":
            return AggregatorNodeExecutor(node, node_name)
        elif node_type == "json_parser_node":
            return JSONParserNodeExecutor(node, node_name)
        elif node_type == "http_request_node":
            return HttpRequestNodeExecutor(node, node_name)
        elif node_type == "get_state_node":
            data = node.data or {}
            config = data.get("config", {})
            return GetStateNodeExecutor(config)
        elif node_type == "set_state_node":
            data = node.data or {}
            config = data.get("config", {})
            return SetStateNodeExecutor(config)
        else:
            # Unknown node type, log warning and fallback to agent
            logger.warning(
                f"[BaseGraphBuilder] Unknown node type '{node_type}', falling back to agent | node_id={node.id}"
            )
            return await self._create_llm_executor(AgentNodeExecutor, node, node_name)

    async def _create_llm_executor(
        self,
        executor_class: Type,
        node: GraphNode,
        node_name: str,
    ) -> Any:
        """Create an LLM-based executor (AgentNodeExecutor or CodeAgentNodeExecutor).

        Handles model resolution, credential extraction, and executor instantiation.
        This is the single place where LLM executor creation logic lives, avoiding
        duplication across _create_node_executor and _create_executor_from_registry.
        """
        resolved_model = await self._resolve_node_llm(node)

        # Extract credentials from the resolved model object
        api_key = self.api_key
        base_url = self.base_url
        llm_model = self.llm_model

        try:
            if hasattr(resolved_model, "openai_api_key"):
                api_key = resolved_model.openai_api_key
            if hasattr(resolved_model, "openai_api_base"):
                base_url = resolved_model.openai_api_base
            if hasattr(resolved_model, "model_name"):
                llm_model = resolved_model.model_name
            elif hasattr(resolved_model, "model"):
                llm_model = resolved_model.model
        except Exception:
            pass

        logger.info(
            f"[BaseGraphBuilder._create_llm_executor] Creating {executor_class.__name__} for node '{node_name}' | "
            f"resolved_model_type={type(resolved_model).__name__} | "
            f"llm_model={llm_model} | api_key={'***' if api_key else None} | base_url={base_url}"
        )

        from app.core.agent.checkpointer.memory_checkpointer import get_checkpointer

        return executor_class(
            node,
            node_name,
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
            max_tokens=self.max_tokens,
            user_id=self.user_id,
            checkpointer=get_checkpointer(),
            resolved_model=resolved_model,
            builder=self,
        )

    async def _create_executor_from_registry(
        self,
        executor_class: Type,
        node: GraphNode,
        node_name: str,
        node_type: str,
    ) -> Any:
        """从注册表创建执行器实例。"""
        # LLM-based executors need model resolution
        if executor_class in (AgentNodeExecutor, CodeAgentNodeExecutor, ConditionAgentNodeExecutor):
            return await self._create_llm_executor(executor_class, node, node_name)
        elif executor_class == ToolNodeExecutor:
            return ToolNodeExecutor(node, node_name, user_id=self.user_id)
        else:
            # Other executors only need node and node_name
            return executor_class(node, node_name)

    async def _resolve_node_llm(self, node: GraphNode) -> Any:
        """
        统一解析节点的语言模型配置。

        优先策略：
        1. ModelService 精确匹配（provider_name + model_name）或名称查找
        2. ModelService 获取数据库默认模型
        3. get_default_model 最终回退

        这个方法可以在子类中被重写以提供不同的解析逻辑。
        """
        data = node.data or {}
        config: Dict[str, Any] = data.get("config", {}) or {}

        # 解析模型引用
        raw_provider = config.get("provider_name") or config.get("provider")
        raw_model = config.get("model_name") or config.get("model") or config.get("name") or self.llm_model
        provider_name, model_name = parse_model_ref(raw_model, raw_provider)

        logger.debug(
            f"[BaseGraphBuilder._resolve_node_llm] Resolving model for node_id={node.id} | "
            f"resolved_provider={provider_name} | resolved_model={model_name}"
        )

        # 策略 1: ModelService 精确/名称匹配
        if self.model_service and model_name:
            result = await self._resolve_by_model_service(provider_name, model_name)
            if result is not None:
                return result

        # 策略 2: ModelService 默认模型
        if self.model_service:
            result = await self._resolve_default_from_service(model_name)
            if result is not None:
                return result

        # 策略 3: 最终回退
        return self._resolve_fallback_model(model_name)

    async def _resolve_by_model_service(
        self, provider_name: Optional[str], model_name: str
    ) -> Any:
        """Try to resolve model via ModelService (exact or name-based lookup)."""
        workspace_id = getattr(self.graph, "workspace_id", None)
        try:
            if provider_name and model_name:
                model = await self.model_service.get_model_instance(
                    user_id=str(self.user_id) if self.user_id else "system",
                    provider_name=provider_name,
                    model_name=model_name,
                    workspace_id=workspace_id,
                    use_default=False,
                )
            else:
                model = await self.model_service.get_runtime_model_by_name(
                    model_name=model_name,
                    workspace_id=workspace_id,
                )
            logger.info(
                f"[BaseGraphBuilder] Resolved model via ModelService | "
                f"provider={provider_name} | model={model_name}"
            )
            return model
        except Exception as e:
            logger.warning(
                f"[BaseGraphBuilder] ModelService resolution failed | "
                f"provider={provider_name} | model={model_name} | error={e} | "
                f"Trying next fallback."
            )
            return None

    async def _resolve_default_from_service(self, model_name: Optional[str]) -> Any:
        """Try to resolve the default model from database via ModelService."""
        try:
            workspace_id = getattr(self.graph, "workspace_id", None)
            default_model = await self.model_service.get_model_instance(
                user_id=str(self.user_id) if self.user_id else "system",
                workspace_id=workspace_id,
                use_default=True,
            )
            logger.info(
                f"[BaseGraphBuilder] Resolved default model from database | "
                f"type={type(default_model).__name__}"
            )
            return default_model
        except Exception as e:
            logger.error(
                f"[BaseGraphBuilder] Failed to get default model from database | "
                f"error={e} | Using final fallback."
            )
            return None

    def _resolve_fallback_model(self, model_name: Optional[str]) -> Any:
        """Final fallback: create model from env/settings defaults."""
        logger.warning(
            f"[BaseGraphBuilder] Using final fallback get_default_model | "
            f"model={model_name}"
        )
        return get_default_model(
            llm_model=model_name,
            api_key=self.api_key,
            base_url=self.base_url,
            max_tokens=self.max_tokens,
        )

    # ==================== Tool Resolution Utilities ====================

    async def _resolve_tools_from_registry(
        self,
        tools: Optional[List[Any]],
        user_id: Optional[str] = None,
    ) -> List[Any]:
        """
        Resolve tools from the global registry.

        This is the unified entry point for tool resolution. It handles:
        - EnhancedTool instances (passed through)
        - String tool names (resolved from registry)
        - MCP tool names in format "server::tool" (resolved with user context)

        Args:
            tools: List of tools (can be strings, EnhancedTool instances, etc.)
            user_id: User ID for MCP tool validation (defaults to self.user_id)

        Returns:
            List of resolved tool instances
        """
        if not tools:
            return []

        # Use instance user_id if not provided
        if user_id is None:
            user_id = self.user_id

        registry = get_global_registry()
        resolved: List[Any] = []

        # Check if MCP tools need resolution
        has_mcp_tools = any(isinstance(t, str) and "::" in str(t) for t in tools)

        if has_mcp_tools and user_id:
            # MCP tools require database session for resolution
            resolved = await self._resolve_tools_with_db(tools, user_id, registry)
        else:
            # Standard tool resolution without database
            resolved = self._resolve_tools_standard(tools, registry)

        logger.debug(f"[BaseGraphBuilder] Resolved {len(resolved)}/{len(tools)} tools")
        return resolved

    async def _resolve_tools_with_db(
        self,
        tools: List[Any],
        user_id: str,
        registry: Any,
    ) -> List[Any]:
        """
        Resolve tools with database session for MCP tool support.

        Args:
            tools: List of tools to resolve
            user_id: User ID for permission checking
            registry: Tool registry instance

        Returns:
            List of resolved tools
        """
        from app.core.database import async_session_factory

        resolved: List[Any] = []

        async with async_session_factory() as db:
            for tool in tools:
                if isinstance(tool, EnhancedTool):
                    resolved.append(tool)
                elif isinstance(tool, str):
                    resolved_tool = await self._resolve_string_tool(tool, user_id, db, registry)
                    resolved.append(resolved_tool)
                else:
                    resolved.append(tool)

        return resolved

    async def _resolve_string_tool(
        self,
        tool_name: str,
        user_id: str,
        db: Any,
        registry: Any,
    ) -> Any:
        """
        Resolve a string tool name to a tool instance.

        Args:
            tool_name: Tool name (either simple name or "server::tool" format)
            user_id: User ID for MCP tool validation
            db: Database session
            registry: Tool registry instance

        Returns:
            Resolved tool instance or original string if unresolved
        """
        from app.core.tools.mcp_tool_utils import resolve_mcp_tool_from_string

        # Try registry first (built-in tools)
        registry_tool = registry.get_tool(tool_name)
        if registry_tool:
            return registry_tool

        # Try MCP tool resolution
        if "::" in tool_name:
            mcp_tool = await resolve_mcp_tool_from_string(tool_name, user_id, db)
            if mcp_tool:
                return mcp_tool

        # Return original if unresolved
        return tool_name

    def _resolve_tools_standard(self, tools: List[Any], registry: Any) -> List[Any]:
        """
        Resolve tools without database session (standard tools only).

        Args:
            tools: List of tools to resolve
            registry: Tool registry instance

        Returns:
            List of resolved tools
        """
        from app.core.tools.mcp_tool_utils import parse_mcp_tool_name

        resolved: List[Any] = []

        for tool in tools:
            if isinstance(tool, EnhancedTool):
                resolved.append(tool)
            elif isinstance(tool, str):
                # Try registry first
                registry_tool = registry.get_tool(tool)
                if registry_tool:
                    resolved.append(registry_tool)
                elif "::" in tool:
                    # Try MCP tool from registry cache
                    server_name, tool_name = parse_mcp_tool_name(tool)
                    if server_name and tool_name:
                        mcp_tool = registry.get_mcp_tool(server_name, tool_name)
                        resolved.append(mcp_tool if mcp_tool else tool)
                    else:
                        resolved.append(tool)
                else:
                    resolved.append(tool)
            else:
                resolved.append(tool)

        return resolved

    # ==================== Middleware Resolution Utilities ====================

    async def _resolve_skill_middleware(
        self,
        node: GraphNode,
        user_id: Optional[str] = None,
        db_session_factory: Optional[Any] = None,
        backend: Optional[Any] = None,
    ) -> Optional[Any]:
        """
        Resolve and create SkillsMiddleware from node configuration.

        Uses deepagents SkillsMiddleware to load skills from backend.
        Skills should be preloaded to /workspace/skills/ via SkillSandboxLoader.

        Args:
            node: GraphNode containing the configuration
            user_id: User ID for permission checking (defaults to self.user_id)
            db_session_factory: Async database session factory (defaults to async_session_factory)
            backend: Required sandbox backend for skill file loading

        Returns:
            SkillsMiddleware instance if skills are configured and backend is available, None otherwise
        """
        from app.core.database import async_session_factory as default_factory

        # Use instance user_id if not provided
        if user_id is None:
            user_id = self.user_id

        # Use default factory if not provided
        if db_session_factory is None:
            db_session_factory = default_factory

        data = node.data or {}
        config = data.get("config", {})

        # Parse skills configuration
        # Explicitly check if skills is None, empty list, or not a list
        skill_ids_raw = config.get("skills")

        # If skills is not configured (None) or empty list, don't enable middleware
        if skill_ids_raw is None:
            return None

        # Ensure skills is a list
        if not isinstance(skill_ids_raw, list):
            logger.warning(
                f"[BaseGraphBuilder] Invalid skills configuration: expected list, got {type(skill_ids_raw).__name__} "
                f"for node '{data.get('label', 'unknown')}'"
            )
            return None

        # If skills list is empty, don't enable middleware
        if len(skill_ids_raw) == 0:
            return None

        # Convert string UUIDs to UUID objects
        skill_ids: List[uuid.UUID] = []
        for sid in skill_ids_raw:
            try:
                if isinstance(sid, str):
                    skill_ids.append(uuid.UUID(sid))
                elif isinstance(sid, uuid.UUID):
                    skill_ids.append(sid)
            except ValueError as e:
                logger.warning(f"[BaseGraphBuilder] Invalid skill UUID '{sid}': {e}")

        # Only create middleware if we have at least one valid skill ID
        if not skill_ids:
            return None

        # deepagents SkillsMiddleware requires backend
        if not backend:
            logger.warning(
                f"[BaseGraphBuilder] No backend available for SkillsMiddleware "
                f"on node '{data.get('label', 'unknown')}'. "
                f"Skills will not be loaded. Ensure skills are preloaded to /workspace/skills/ "
                f"and backend is provided."
            )
            return None

        try:
            from deepagents.middleware.skills import SkillsMiddleware

            # Use deepagents SkillsMiddleware
            # Skills should already be preloaded to /workspace/skills/ via SkillSandboxLoader
            skills_middleware = SkillsMiddleware(
                backend=backend,
                sources=["/workspace/skills/"],  # Path where skills are preloaded
            )
            logger.info(
                f"[BaseGraphBuilder] Using deepagents SkillsMiddleware for {len(skill_ids)} skill(s) "
                f"on node '{data.get('label', 'unknown')}' "
                f"(reading from /workspace/skills/)"
            )
            return skills_middleware
        except ImportError:
            logger.error(
                f"[BaseGraphBuilder] deepagents SkillsMiddleware not available. "
                f"Please ensure deepagents is installed. "
                f"Skills will not be loaded for node '{data.get('label', 'unknown')}'."
            )
            return None
        except Exception as e:
            logger.error(
                f"[BaseGraphBuilder] Failed to create deepagents SkillsMiddleware: {e}. "
                f"Skills will not be loaded for node '{data.get('label', 'unknown')}'."
            )
            return None

    async def _resolve_memory_middleware(
        self,
        node: GraphNode,
        user_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Resolve and create AgentMemoryIterationMiddleware from node configuration.

        Args:
            node: GraphNode containing the configuration
            user_id: User ID for memory service (defaults to self.user_id)

        Returns:
            AgentMemoryIterationMiddleware instance if memory is enabled, None otherwise
        """
        from app.core.agent.memory.manager import MemoryManager
        from app.core.agent.midware.memory_iteration_with_db import AgentMemoryIterationMiddleware
        from app.services.memory_service import MemoryService

        # Use instance user_id if not provided
        if user_id is None:
            user_id = self.user_id

        data = node.data or {}
        config = data.get("config", {})

        # Check if memory is enabled
        enable_memory = config.get("enableMemory", False)
        if not enable_memory:
            return None

        # Get memory model using unified parse_model_ref
        # Supports: "provider:model", memoryProvider + memoryModel, or plain model name
        raw_memory_provider = config.get("memoryProvider") or config.get("memory_provider")
        raw_memory_model = config.get("memoryModel")

        if not raw_memory_model:
            logger.warning(
                f"[BaseGraphBuilder] enableMemory=True but memoryModel not specified "
                f"for node '{data.get('label', 'unknown')}'. Skipping memory middleware."
            )
            return None

        memory_provider_name, memory_model_name = parse_model_ref(raw_memory_model, raw_memory_provider)

        if not memory_model_name:
            logger.warning(
                f"[BaseGraphBuilder] enableMemory=True but memoryModel could not be parsed "
                f"for node '{data.get('label', 'unknown')}'. raw_value={raw_memory_model}. Skipping memory middleware."
            )
            return None

        # Get memory prompt (optional)
        memory_prompt = config.get("memoryPrompt")

        try:
            # Resolve memory model using model_service
            memory_model = None
            if self.model_service and memory_model_name:
                try:
                    workspace_id = getattr(self.graph, "workspace_id", None)
                    # If provider is known, prefer exact match
                    if memory_provider_name:
                        memory_model = await self.model_service.get_model_instance(
                            user_id=str(self.user_id) if self.user_id else "system",
                            provider_name=memory_provider_name,
                            model_name=str(memory_model_name),
                            workspace_id=workspace_id,
                            use_default=False,
                        )
                        logger.info(
                            f"[BaseGraphBuilder._resolve_memory_middleware] Successfully resolved memory model "
                            f"via ModelService.get_model_instance | provider_name={memory_provider_name} | model_name={memory_model_name}"
                        )
                    else:
                        memory_model = await self.model_service.get_runtime_model_by_name(
                            model_name=str(memory_model_name),
                            workspace_id=workspace_id,
                        )
                        logger.info(
                            f"[BaseGraphBuilder._resolve_memory_middleware] Successfully resolved memory model "
                            f"via ModelService.get_runtime_model_by_name | model_name={memory_model_name}"
                        )
                except Exception as e:
                    logger.warning(
                        f"[BaseGraphBuilder._resolve_memory_middleware] Failed to resolve model via ModelService | "
                        f"provider_name={memory_provider_name} | model_name={memory_model_name} | error={type(e).__name__}: {e} | "
                        f"Falling back to get_default_model."
                    )

            # Fallback to get_default_model if model_service failed or not available
            if memory_model is None:
                memory_model = get_default_model(
                    llm_model=str(memory_model_name),
                    api_key=self.api_key,
                    base_url=self.base_url,
                    max_tokens=self.max_tokens,
                )
                logger.info(
                    f"[BaseGraphBuilder._resolve_memory_middleware] Using fallback get_default_model | "
                    f"model_name={memory_model_name}"
                )

            # Create MemoryService (it will manage its own database sessions)
            memory_service = MemoryService()

            # Create MemoryManager
            memory_manager = MemoryManager(
                model=memory_model,
                memory_capture_instructions=memory_prompt,
                db=memory_service,
            )

            # Create AgentMemoryIterationMiddleware
            memory_middleware = AgentMemoryIterationMiddleware(
                memory_manager=memory_manager,
                retrieval_method="last_n",
                retrieval_limit=5,
                context_header="## 相关用户记忆",
                enable_writeback=True,
                capture_source="user",
                user_id=user_id,  # 传递 user_id 到中间件
            )

            logger.debug(
                f"[BaseGraphBuilder] Created AgentMemoryIterationMiddleware "
                f"for node '{data.get('label', 'unknown')}' with model '{memory_model_name}'"
            )
            return memory_middleware

        except Exception as e:
            logger.warning(
                f"[BaseGraphBuilder] Failed to create AgentMemoryIterationMiddleware "
                f"for node '{data.get('label', 'unknown')}': {e}"
            )
            return None

    async def resolve_middleware_for_node(
        self,
        node: GraphNode,
        user_id: Optional[str] = None,
        db_session_factory: Optional[Any] = None,
    ) -> List[Any]:
        """
        Parse and create middleware instances from node configuration.

        Uses a strategy pattern to resolve different middleware types.
        Each middleware resolver is called independently, making it easy to add new types.

        Currently supports:
        - SkillMiddleware: Created when `skills` config contains skill UUIDs
        - AgentMemoryIterationMiddleware: Created when `enableMemory` is true

        To add a new middleware type:
        1. Create a `_resolve_<name>_middleware` method following the same pattern
        2. Add it to the `_middleware_resolvers` list below

        Args:
            node: GraphNode containing the configuration
            user_id: User ID for permission checking (defaults to self.user_id)
            db_session_factory: Async database session factory (defaults to async_session_factory)

        Returns:
            List of middleware instances configured for the node
        """
        from app.core.database import async_session_factory as default_factory

        # Use instance user_id if not provided
        if user_id is None:
            user_id = self.user_id

        # Use default factory if not provided
        if db_session_factory is None:
            db_session_factory = default_factory

        # Check if backend is available (for skill loading)
        # This will be set by DeepAgentsGraphBuilder if backend is created
        backend = getattr(self, "_current_node_backend", None)

        # Define middleware resolvers in execution order
        # Each resolver should return Optional[Any] (middleware instance or None)
        async def resolve_skill(node, uid, db_factory):
            return await self._resolve_skill_middleware(node, uid, db_factory, backend)

        async def resolve_memory(node, uid, db_factory):
            return await self._resolve_memory_middleware(node, uid)

        _middleware_resolvers = [
            resolve_skill,
            resolve_memory,
            # Future middleware resolvers can be added here:
            # resolve_custom,
        ]

        # Resolve all middleware types
        middleware: List[Any] = []
        for resolver in _middleware_resolvers:
            try:
                mw = await resolver(node, user_id, db_session_factory)
                if mw:
                    middleware.append(mw)
            except Exception as e:
                logger.warning(
                    f"[BaseGraphBuilder.resolve_middleware_for_node] "
                    f"Middleware resolver {resolver.__name__} failed: {e}"
                )

        return middleware

    # ==================== Configuration Utilities ====================

    def _get_recursion_limit(self) -> int:
        """
        Get the recursion limit from graph config or use default.

        Reads from self.graph.config["recursion_limit"] if available,
        otherwise falls back to DEFAULT_RECURSION_LIMIT.

        Returns:
            Configured recursion limit value
        """
        if self.graph and hasattr(self.graph, "config") and self.graph.config:
            config = self.graph.config
            if isinstance(config, dict):
                limit = config.get("recursion_limit", DEFAULT_RECURSION_LIMIT)
                return int(limit) if limit is not None else DEFAULT_RECURSION_LIMIT
        return DEFAULT_RECURSION_LIMIT

    # ==================== Graph Validation ====================

    def validate_graph_structure(self) -> List[str]:
        """
        Validate graph structure at compile time.

        Checks:
        - Router nodes have all branches connected
        - Handle ID to route_key mappings are complete
        - Loop structures are valid
        - No isolated nodes
        - No invalid routes

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Check for isolated nodes (no incoming or outgoing edges)
        # Skip this check for single-node graphs - they are valid as START → Node → END
        if len(self.nodes) > 1:
            node_ids = {node.id for node in self.nodes}
            nodes_with_incoming = {edge.target_node_id for edge in self.edges}
            nodes_with_outgoing = {edge.source_node_id for edge in self.edges}

            isolated_nodes = node_ids - nodes_with_incoming - nodes_with_outgoing
            if isolated_nodes:
                for node_id in isolated_nodes:
                    node = self._node_map.get(node_id)
                    if node:
                        label = (node.data or {}).get("label", str(node_id))
                        errors.append(f"Isolated node found: '{label}' (no incoming or outgoing edges)")

        # Validate router nodes
        for node in self.nodes:
            node_type = self._get_node_type(node)
            if node_type == "router_node":
                # Check that router has outgoing edges
                router_edges = [e for e in self.edges if e.source_node_id == node.id]
                if not router_edges:
                    label = (node.data or {}).get("label", str(node.id))
                    errors.append(f"Router node '{label}' has no outgoing edges")

                # Check that edges have route_key or source_handle_id
                for edge in router_edges:
                    edge_data = edge.data or {}
                    if not edge_data.get("route_key") and not edge_data.get("source_handle_id"):
                        label = (node.data or {}).get("label", str(node.id))
                        errors.append(f"Router node '{label}' has edge without route_key or source_handle_id")

        # Validate loop condition nodes
        for node in self.nodes:
            node_type = self._get_node_type(node)
            if node_type == "loop_condition_node":
                # Check that loop has continue_loop and exit_loop edges
                loop_edges = [e for e in self.edges if e.source_node_id == node.id]
                route_keys = {e.data.get("route_key") for e in loop_edges if e.data}

                if "continue_loop" not in route_keys and "exit_loop" not in route_keys:
                    label = (node.data or {}).get("label", str(node.id))
                    errors.append(f"Loop condition node '{label}' missing continue_loop or exit_loop edges")

                # Check for loop cycles (potential infinite loops)
                if self._detect_potential_cycles(node.id):
                    label = (node.data or {}).get("label", str(node.id))
                    errors.append(f"Loop condition node '{label}' may create infinite loop - check for cycles")

        # Validate for orphaned conditional edges
        conditional_sources = set()
        for edge in self.edges:
            edge_data = edge.data or {}
            if edge_data.get("edge_type") == "conditional":
                conditional_sources.add(edge.source_node_id)

        for source_id in conditional_sources:
            source_node = self._node_map.get(source_id)
            if source_node:
                node_type = self._get_node_type(source_node)
                if node_type not in ["router_node", "condition", "loop_condition_node"]:
                    label = (source_node.data or {}).get("label", str(source_id))
                    errors.append(f"Node '{label}' has conditional edges but is not a conditional node type")

        return errors

    def _detect_potential_cycles(self, start_node_id: uuid.UUID, visited: Optional[Set[str]] = None) -> bool:
        """
        Detect potential cycles starting from a node.
        This is a simplified cycle detection for loop validation.
        """
        if visited is None:
            visited = set()

        node_key = str(start_node_id)
        if node_key in visited:
            return True

        visited.add(node_key)

        # Check outgoing edges
        for edge in self.edges:
            if edge.source_node_id == start_node_id:
                # For loop back edges, check if they lead back to potential loop starters
                edge_data = edge.data or {}
                if edge_data.get("edge_type") == "loop_back":
                    target_node = self._node_map.get(edge.target_node_id)
                    if target_node and self._get_node_type(target_node) == "loop_condition_node":
                        if self._detect_potential_cycles(edge.target_node_id, visited.copy()):
                            return True

        visited.remove(node_key)
        return False

    def validate_handle_to_route_mapping(self) -> List[str]:
        """
        Validate that React Flow Handle IDs map correctly to route keys.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        for node in self.nodes:
            node_type = self._get_node_type(node)
            if node_type in ["router_node", "condition"]:
                # Collect edges from this node
                node_edges = [e for e in self.edges if e.source_node_id == node.id]

                # Check handle_id to route_key consistency
                handle_to_route: Dict[str, str] = {}
                for edge in node_edges:
                    edge_data = edge.data or {}
                    handle_id = edge_data.get("source_handle_id")
                    route_key = edge_data.get("route_key")

                    if handle_id and route_key:
                        if handle_id in handle_to_route:
                            if handle_to_route[handle_id] != route_key:
                                label = (node.data or {}).get("label", str(node.id))
                                errors.append(
                                    f"Node '{label}': Handle '{handle_id}' maps to multiple route_keys: "
                                    f"'{handle_to_route[handle_id]}' and '{route_key}'"
                                )
                        else:
                            handle_to_route[handle_id] = route_key

        return errors

    @abstractmethod
    def build(self) -> CompiledStateGraph:
        """Build and compile the StateGraph. Must be implemented by subclasses."""
        pass
