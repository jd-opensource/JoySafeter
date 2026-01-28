"""DeepAgents Graph Builder - Two-level star structure: Root (Manager) → Children (Workers)."""

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:
    pass
# DeepAgents library imports - required
from deepagents import create_deep_agent
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.graph.base_graph_builder import (
    BaseGraphBuilder,
)
from app.core.graph.deep_agents.backend_factory import BackendFactory
from app.core.graph.deep_agents.backend_manager import DeepAgentsBackendManager
from app.core.graph.deep_agents.node_config import AgentConfig
from app.core.graph.deep_agents.node_factory import DeepAgentsNodeBuilder
from app.core.graph.deep_agents.skills_manager import DeepAgentsSkillsManager
from app.models.graph import GraphNode

# Constants
LOG_PREFIX = "[DeepAgentsBuilder]"


class DeepAgentsGraphBuilder(BaseGraphBuilder):
    """Two-level star structure: Root (DeepAgent) → Children (CompiledSubAgent)."""

    def __init__(self, *args, **kwargs):
        """Initialize DeepAgentsGraphBuilder with component managers."""
        super().__init__(*args, **kwargs)
        self._backend_manager = DeepAgentsBackendManager(self.nodes)
        self._skills_manager = DeepAgentsSkillsManager(self.user_id)
        self._node_builder = DeepAgentsNodeBuilder(builder=self)

    async def build(self) -> CompiledStateGraph[Any, None, Any, Any]:  # type: ignore[override]
        """Build two-level star structure: Root (Manager) → Children (Workers)."""
        if not self.nodes:
            raise ValueError("No nodes provided for DeepAgents graph")

        try:
            await self._setup_shared_backend()
            root_node = self._select_and_validate_root()
            result = await self._build_graph(root_node)
            return result  # type: ignore
        except Exception as e:
            logger.exception(f"{LOG_PREFIX} Build failed: {e}")
            await self._backend_manager.cleanup_shared_backend()
            raise

    async def _setup_shared_backend(self) -> None:
        """Setup shared Docker backend if needed."""
        needs_docker = self._backend_manager.should_create_shared_backend(self._skills_manager.has_valid_skills_config)

        if needs_docker:
            try:
                await self._backend_manager.create_shared_backend()
                logger.info(
                    f"{LOG_PREFIX} Created shared Docker backend: "
                    f"id={getattr(self._backend_manager.shared_backend, 'id', 'unknown')}"
                )
            except Exception as e:
                logger.error(f"{LOG_PREFIX} Failed to create shared Docker backend: {e}")

    def _select_and_validate_root(self) -> GraphNode:
        """Select and validate root node."""
        root_nodes = self._find_root_nodes()
        if not root_nodes:
            raise ValueError("No root nodes found - graph must have at least one root node")

        # Check for multiple root nodes (disconnected graph structure)
        # Multiple root nodes indicate disconnected components, which is problematic
        if len(root_nodes) > 1:
            raise ValueError(
                f"Graph has {len(root_nodes)} root nodes (disconnected components). "
                "Graph should have only one entry point. "
                "Please connect all nodes or remove unused nodes."
            )

        root_node = self._select_root_node(root_nodes)
        if not root_node:
            raise ValueError("Cannot select root node - multiple roots without DeepAgents enabled")

        return root_node

    async def _build_graph(self, root_node: GraphNode) -> Any:
        """Build the graph structure from root node."""
        root_config = await AgentConfig.from_node(root_node, self, self._node_id_to_name)
        root_label = root_config.label or root_config.name
        logger.info(f"{LOG_PREFIX} Building from root: '{root_label}'")

        children = self._get_direct_children(root_node)

        if not children:
            # Root without children: build as standalone DeepAgent
            if not self._is_deep_agents_enabled(root_node):
                raise ValueError("Root node must have DeepAgents enabled")
            final_agent = await self._node_builder.build_root_node(root_node, root_label)
        else:
            # Root with children: build workers first, then manager
            subagents = []
            for child in children:
                await AgentConfig.from_node(child, self, self._node_id_to_name)
                subagents.append(await self._node_builder.build_worker_node(child))
            final_agent = await self._node_builder.build_manager_node(root_node, root_label, subagents, is_root=True)

        return self._finalize_agent(final_agent)

    def _find_root_nodes(self) -> list[GraphNode]:
        """Find root nodes (no incoming edges)."""
        target_ids = {edge.target_node_id for edge in self.edges}
        return [n for n in self.nodes if n.id not in target_ids]

    def _select_root_node(self, roots: list[GraphNode]) -> GraphNode | None:
        """Select root: prefer DeepAgents-enabled, else single root."""
        if not roots:
            return None
        deep_roots = [n for n in roots if self._is_deep_agents_enabled(n)]
        if deep_roots:
            return deep_roots[0]
        return roots[0] if len(roots) == 1 else None

    def _get_checkpointer(self) -> Any | None:
        """Get checkpointer for root agent."""
        from app.core.agent.checkpointer.checkpointer import get_checkpointer

        return get_checkpointer()

    def _compile_state_graph(self, agent: StateGraph) -> CompiledStateGraph:
        """Compile StateGraph to CompiledStateGraph."""
        checkpointer = self._get_checkpointer()
        return agent.compile(checkpointer=checkpointer, interrupt_before=[], interrupt_after=[])

    def _configure_agent(self, agent: Any) -> Any:
        """Apply runtime configuration to agent."""
        recursion_limit = self._get_recursion_limit()
        return agent.with_config({"recursion_limit": recursion_limit})

    def _finalize_agent(self, agent: Any) -> Any:
        """Finalize agent: compile if needed, configure, and attach cleanup."""
        # Compile StateGraph if needed
        if isinstance(agent, StateGraph):
            agent = self._compile_state_graph(agent)

        # Apply runtime configuration
        if isinstance(agent, CompiledStateGraph):
            agent = self._configure_agent(agent)
        elif isinstance(agent, dict):
            raise ValueError("Received dict instead of Runnable - DeepAgents build failed")

        # Attach cleanup if shared backend exists
        if agent and self._backend_manager.shared_backend:
            backend_manager = self._backend_manager

            async def cleanup():
                await backend_manager.cleanup_shared_backend()

            agent._cleanup_backend = cleanup

        return agent

    # ==================== Node Configuration Helpers ====================
    # These methods are used by AgentConfig.from_node() for parsing node configuration
    # They provide controlled access to builder capabilities while maintaining encapsulation

    def get_node_id_to_name(self) -> dict:
        """Get node ID to name mapping - for AgentConfig use."""
        return self._node_id_to_name

    def has_valid_skills_config(self, skill_ids_raw: Any) -> bool:
        """Check if skills config is valid - for AgentConfig use."""
        result = self._skills_manager.has_valid_skills_config(skill_ids_raw)
        return bool(result) if result is not None else False

    async def get_backend_for_node(self, node: GraphNode, has_skills: bool) -> Optional[Any]:
        """Get backend for node - for AgentConfig use."""
        return await self._backend_manager.get_backend_for_node(node, has_skills, self._create_backend_for_node)

    async def preload_skills_to_backend(self, node: GraphNode, backend: Any) -> None:
        """Preload skills to backend - for AgentConfig use."""
        await self._skills_manager.preload_skills_to_backend(node, backend)

    def get_skills_paths(self, has_skills: bool, backend: Any) -> Optional[list[str]]:
        """Get skills paths - for AgentConfig use."""
        result = self._skills_manager.get_skills_paths(has_skills, backend)
        if result is None:
            return None
        if isinstance(result, list):
            return [str(item) for item in result]
        return None

    def get_shared_backend(self) -> Optional[Any]:
        """Get shared backend instance - for NodeBuilder use."""
        return self._backend_manager.shared_backend

    def is_shared_backend_creation_failed(self) -> bool:
        """Check if shared backend creation failed - for NodeBuilder use."""
        result = self._backend_manager.shared_backend_creation_failed
        return bool(result) if result is not None else False

    async def resolve_middleware_for_node(
        self,
        node: GraphNode,
        user_id: Optional[str] = None,
        db_session_factory: Optional[Any] = None,
    ) -> list[Any]:
        """Resolve middleware (excludes SkillsMiddleware - handled via skills param)."""
        from app.core.database import async_session_factory as default_factory

        user_id = user_id or self.user_id
        db_session_factory = db_session_factory or default_factory
        middleware = []
        try:
            if mw := await self._resolve_memory_middleware(node, user_id):
                middleware.append(mw)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Middleware resolver failed: {e}")
        return middleware

    async def resolve_middleware_for_node_with_backend(
        self, node: GraphNode, backend: Any, user_id: Optional[str] = None
    ) -> list[Any]:
        """Resolve middleware with backend context - for AgentConfig use."""
        self._current_node_backend = backend
        try:
            return await self.resolve_middleware_for_node(node, user_id)
        finally:
            self._current_node_backend = None

    async def _create_backend_for_node(self, node: GraphNode) -> Any:
        """Create backend with fallback - used by backend_manager.get_backend_for_node().

        从节点配置中读取 workspace_dir 或 workspaceSubdir，如果没有配置则使用 graph.name。
        """
        # 从节点配置读取自定义子目录名称
        data = node.data or {}
        config = data.get("config", {})
        workspace_subdir = config.get("workspace_dir") or config.get("workspaceSubdir")

        # 如果没有配置，使用 graph.name 作为默认值
        if not workspace_subdir:
            workspace_subdir = self.graph.name if hasattr(self.graph, "name") and self.graph.name else None

        return BackendFactory.create_backend_with_fallback(
            node, user_id=self.user_id, workspace_subdir=workspace_subdir
        )

    # ==================== DeepAgent Creation ====================

    def _create_deep_agent(
        self,
        model: Any,
        system_prompt: str | None,
        tools: list[Any],
        subagents: list[Any],
        middleware: list[Any],
        name: str,
        is_root: bool = False,
        skills: list[str] | None = None,
        backend: Any | None = None,
    ) -> Any:
        """Create DeepAgent - returns StateGraph or CompiledStateGraph."""
        kwargs = {
            "model": model,
            "system_prompt": system_prompt,
            "tools": tools,
            "subagents": subagents,
            "middleware": middleware,
            "name": name,
        }
        # Only root agents need checkpointer
        if is_root:
            kwargs["checkpointer"] = self._get_checkpointer()
        if skills:
            kwargs["skills"] = skills
        if backend:
            kwargs["backend"] = backend
        return create_deep_agent(**kwargs)
