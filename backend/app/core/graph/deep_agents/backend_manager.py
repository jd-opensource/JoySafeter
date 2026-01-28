"""Backend manager for DeepAgents graph builder.

Manages shared Docker backend lifecycle for the entire graph.
"""

from typing import TYPE_CHECKING, Any, Callable, Optional

from loguru import logger

if TYPE_CHECKING:
    from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter
    from app.models.graph import GraphNode

LOG_PREFIX = "[BackendManager]"


class DeepAgentsBackendManager:
    """Manages shared Docker backend for DeepAgents graph."""

    def __init__(self, nodes: list["GraphNode"]):
        """Initialize backend manager.

        Args:
            nodes: List of graph nodes to analyze for backend requirements
        """
        self.nodes = nodes
        self._shared_backend: Optional["PydanticSandboxAdapter"] = None
        self._backend_cleaned_up: bool = False
        self._shared_backend_creation_failed: bool = False

    def should_create_shared_backend(self, has_valid_skills_config: Callable[[Any], bool]) -> bool:
        """Check if shared Docker backend should be created.

        Args:
            has_valid_skills_config: Function to check if skills config is valid

        Returns:
            True if shared backend should be created
        """
        for node in self.nodes:
            data = node.data or {}
            config = data.get("config", {})

            # Check if node explicitly configured filesystem backend
            # If so, don't create shared Docker backend for this node
            backend_type = config.get("backend_type")
            if backend_type == "filesystem":
                continue  # Skip this node, use filesystem backend instead

            if has_valid_skills_config(config.get("skills")):
                return True

            if data.get("type") == "code_agent":
                executor_type = config.get("executor_type", "local")
                if executor_type in ("docker", "auto"):
                    return True

        return False

    async def create_shared_backend(self) -> "PydanticSandboxAdapter":
        """Create shared Docker backend for the entire graph.

        Returns:
            PydanticSandboxAdapter instance ready for use

        Raises:
            ImportError: If pydantic-ai-backend[docker] is not available
            RuntimeError: If Docker backend creation fails
        """
        from app.core.agent.backends.pydantic_adapter import (
            PYDANTIC_BACKEND_AVAILABLE,
            PydanticSandboxAdapter,
        )

        if not PYDANTIC_BACKEND_AVAILABLE:
            raise ImportError(
                "pydantic-ai-backend[docker] is required for shared Docker backend. "
                "Install with: pip install pydantic-ai-backend[docker]"
            )

        docker_image = "python:3.12-slim"
        for node in self.nodes:
            data = node.data or {}
            if data.get("type") == "code_agent":
                config = data.get("config", {})
                docker_image = config.get("docker_image", docker_image)
                break

        try:
            backend = PydanticSandboxAdapter(
                image=docker_image,
                memory_limit="1g",
                network_mode="none",
                working_dir="/workspace",
            )
            if hasattr(backend, "is_started") and backend.is_started():
                logger.debug(f"{LOG_PREFIX} Shared Docker backend started: id={backend.id}")
            self._shared_backend = backend
            return backend
        except Exception as e:
            self._shared_backend_creation_failed = True
            raise RuntimeError(f"{LOG_PREFIX} Failed to create shared Docker backend: {e}") from e

    async def cleanup_shared_backend(self) -> None:
        """Clean up shared Docker backend."""
        if self._backend_cleaned_up:
            return

        if self._shared_backend:
            try:
                if hasattr(self._shared_backend, "cleanup"):
                    self._shared_backend.cleanup()
                logger.info(f"{LOG_PREFIX} Cleaned up shared Docker backend")
            except Exception as e:
                logger.warning(f"{LOG_PREFIX} Failed to cleanup shared backend: {e}")
            finally:
                self._shared_backend = None
                self._backend_cleaned_up = True

    async def get_backend_for_node(
        self,
        node: "GraphNode",
        has_skills: bool,
        create_backend_for_node: Callable[..., Any],
    ) -> Optional[Any]:
        """Get backend for a node (shared or node-specific).

        Priority logic:
        1. If node has explicit backend_type configuration, ALWAYS use node-specific backend (respect user's choice)
        2. If node has skills but no explicit backend_type, prefer shared backend (if available) for data persistence
        3. If no shared backend but has skills, create node-specific backend
        4. Otherwise return None

        Args:
            node: GraphNode to get backend for
            has_skills: Whether node has skills configured
            create_backend_for_node: Async function to create node-specific backend

        Returns:
            Backend instance or None
        """
        data = node.data or {}
        config = data.get("config", {})
        backend_type = config.get("backend_type")

        # Priority 1: If node has explicit backend_type configuration, ALWAYS respect it
        # This ensures user's choice (filesystem or docker) is honored, even if skills are configured
        if backend_type:
            logger.debug(
                f"{LOG_PREFIX} Node '{data.get('label', 'unknown')}' has explicit backend_type='{backend_type}', "
                f"using node-specific backend (has_skills={has_skills})"
            )
            return await create_backend_for_node(node)

        # Priority 2: For nodes with skills but no explicit backend_type,
        # prefer shared backend for data persistence
        if has_skills:
            if self._shared_backend and not self._shared_backend_creation_failed:
                logger.debug(
                    f"{LOG_PREFIX} Node '{data.get('label', 'unknown')}' has skills but no explicit backend_type, "
                    "using shared backend"
                )
                return self._shared_backend
            else:
                # No shared backend available, create node-specific backend
                logger.debug(
                    f"{LOG_PREFIX} Node '{data.get('label', 'unknown')}' has skills but no shared backend, "
                    "creating node-specific backend"
                )
                return await create_backend_for_node(node)

        # No skills and no explicit backend_type, return None
        return None

    @property
    def shared_backend(self) -> Optional["PydanticSandboxAdapter"]:
        """Get shared backend instance."""
        return self._shared_backend

    @property
    def backend_cleaned_up(self) -> bool:
        """Check if backend has been cleaned up."""
        return self._backend_cleaned_up

    @property
    def shared_backend_creation_failed(self) -> bool:
        """Check if backend creation failed."""
        return self._shared_backend_creation_failed
