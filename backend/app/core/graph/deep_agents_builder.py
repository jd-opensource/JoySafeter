"""DeepAgents Graph Builder - Two-level star structure: Root (Manager) → Children (Workers)."""

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:
    from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

# DeepAgents library imports - required
from deepagents import create_deep_agent
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.database import async_session_factory
from app.core.graph.base_graph_builder import (
    BaseGraphBuilder,
)
from app.core.graph.deep_agents.node_config import AgentConfig
from app.core.graph.deep_agents.node_factory import DeepAgentsNodeBuilder
from app.core.graph.deep_agents.skills_manager import DeepAgentsSkillsManager
from app.models.graph import GraphNode
from app.services.sandbox_manager import SandboxManagerService

# Constants
LOG_PREFIX = "[DeepAgentsBuilder]"


class DeepAgentsGraphBuilder(BaseGraphBuilder):
    """Two-level star structure: Root (DeepAgent) → Children (CompiledSubAgent).

    Manages a single shared Docker backend for all nodes in the graph.
    """

    def __init__(self, *args, **kwargs):
        """Initialize DeepAgentsGraphBuilder with component managers."""
        # Extract file_emitter before passing to super
        self._file_emitter = kwargs.pop("file_emitter", None)
        super().__init__(*args, **kwargs)
        self._shared_backend: Optional["PydanticSandboxAdapter"] = None
        self._skills_manager = DeepAgentsSkillsManager(self.user_id)
        self._node_builder = DeepAgentsNodeBuilder(builder=self)

    async def build(self) -> CompiledStateGraph[Any, None, Any, Any]:  # type: ignore[override]
        """Build two-level star structure: Root (Manager) → Children (Workers)."""
        if not self.nodes:
            raise ValueError("No nodes provided for DeepAgents graph")

        try:
            # Get user's shared sandbox if needed (reuses existing sandbox from pool)
            if self._needs_docker_backend():
                self._shared_backend = await self._get_user_sandbox()
                logger.info(
                    f"{LOG_PREFIX} Using user sandbox: id={getattr(self._shared_backend, 'id', 'unknown')}, user_id={self.user_id}"
                )
                if self._shared_backend and self._file_emitter:
                    from app.core.agent.backends.file_tracking_proxy import FileTrackingProxy
                    self._shared_backend = FileTrackingProxy(self._shared_backend, self._file_emitter)
                    logger.info(f"{LOG_PREFIX} Wrapped backend with FileTrackingProxy")

            root_node = self._select_and_validate_root()
            result = await self._build_graph(root_node)
            return result  # type: ignore
        except Exception as e:
            logger.exception(f"{LOG_PREFIX} Build failed: {e}")
            await self._cleanup_backend()
            raise

    def _needs_docker_backend(self) -> bool:
        """Check if any node needs Docker backend."""
        for node in self.nodes:
            data = node.data or {}
            config = data.get("config", {})

            # Skip nodes explicitly configured with filesystem backend
            if config.get("backend_type") == "filesystem":
                continue

            # Check for skills
            if self._skills_manager.has_valid_skills_config(config.get("skills")):
                return True

            # Check for code_agent with docker executor
            if data.get("type") == "code_agent":
                executor_type = config.get("executor_type", "local")
                if executor_type in ("docker", "auto"):
                    return True

        return False

    async def _get_user_sandbox(self) -> "PydanticSandboxAdapter":
        """Get user's private sandbox from SandboxManagerService.

        This method ensures that all graph executions for a user share
        the same sandbox container, providing:
        - Per-user isolation
        - Sandbox pooling and reuse
        - Persistent workspace across sessions
        """
        if not self.user_id:
            raise ValueError(f"{LOG_PREFIX} user_id is required for sandbox execution")

        try:
            async with async_session_factory() as session:
                service = SandboxManagerService(session)
                adapter = await service.ensure_sandbox_running(str(self.user_id))
                logger.info(f"{LOG_PREFIX} Got user sandbox: id={adapter.id}, user_id={self.user_id}")
                return adapter
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Failed to get user sandbox for user_id={self.user_id}: {e}")
            raise RuntimeError(f"{LOG_PREFIX} Failed to get user sandbox: {e}") from e

    async def _cleanup_backend(self) -> None:
        """Release shared backend reference and decrement pool active_count.

        Note: We do NOT cleanup/destroy the sandbox container here because
        the sandbox is managed by SandboxManagerService and shared across
        multiple graph executions for the same user. The sandbox pool handles
        the actual lifecycle management (idle timeout, etc.).
        """
        if self._shared_backend:
            sandbox_id = getattr(self._shared_backend, "id", None)
            logger.debug(f"{LOG_PREFIX} Releasing reference to user sandbox: id={sandbox_id or 'unknown'}")
            # Release pool reference count so idle cleanup can work
            if sandbox_id:
                try:
                    from app.services.sandbox_manager import _sandbox_pool

                    await _sandbox_pool.release(sandbox_id)
                except Exception as e:
                    logger.warning(f"{LOG_PREFIX} Failed to release pool ref for {sandbox_id}: {e}")
            # Release the Python reference, don't destroy the container
            self._shared_backend = None

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

        # Attach cleanup and optional artifact export if shared backend exists
        if agent and self._shared_backend:

            async def cleanup():
                await self._cleanup_backend()

            agent._cleanup_backend = cleanup

            # Allow chat to export Docker working dir to artifact run dir before cleanup
            try:
                from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

                if isinstance(self._shared_backend, PydanticSandboxAdapter):
                    agent._export_artifacts_to = self._shared_backend.export_working_dir_to
            except Exception:
                pass

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

    def get_backend(self) -> Optional[Any]:
        """Get shared backend instance - all nodes use this single backend."""
        return self._shared_backend

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
