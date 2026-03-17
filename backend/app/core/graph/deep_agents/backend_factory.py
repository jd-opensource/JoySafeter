"""Backend factory for DeepAgents graph builder.

This module provides filesystem backend creation only.
Docker backends are managed centrally by DeepAgentsGraphBuilder.

When thread_id and run_id are provided, root_dir is set to the unified agent
artifacts directory (AGENT_ARTIFACTS_ROOT/{user_id}/{thread_id}/{run_id}/)
so that run outputs are persisted and exposed via the artifacts API.
"""

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from app.core.agent.artifacts.collector import resolve_artifacts_root
from app.utils.path_utils import sanitize_path_component

if TYPE_CHECKING:
    from app.models.graph import GraphNode

LOG_PREFIX = "[BackendFactory]"


class BackendFactory:
    """Factory for creating filesystem backend instances."""

    @staticmethod
    def _sanitize_path_component(value: Optional[str], default: str = "default", max_length: int = 100) -> str:
        """清理路径组件，防止路径遍历攻击。

        Args:
            value: 原始值
            default: 默认值（如果 value 为 None 或无效）
            max_length: 最大长度限制

        Returns:
            清理后的安全路径组件
        """
        return sanitize_path_component(value, default=default, max_length=max_length)

    @staticmethod
    def _create_filesystem_backend(
        node: "GraphNode",
        node_label: str,
        user_id: Optional[str] = None,
        workspace_subdir: Optional[str] = None,
        thread_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Any:
        """Create Filesystem backend using deepAgents FilesystemBackend.

        When thread_id and run_id are provided, uses artifact storage:
          AGENT_ARTIFACTS_ROOT/{user_id}/{thread_id}/{run_id}/

        Otherwise uses legacy path (no per-run isolation):
          DEEPAGENTS_WORKSPACE_ROOT/{user_id}/{workspace_subdir}/

        No directory is deleted; each run gets a new path when run_id is set.

        Args:
            node: GraphNode to extract node ID from
            node_label: Node label for logging
            user_id: User ID for workspace directory isolation (will be sanitized)
            workspace_subdir: Custom subdirectory name (will be sanitized, defaults to "default")
            thread_id: Thread/conversation ID for artifact path (optional)
            run_id: Run ID for artifact path (optional)

        Returns:
            FilesystemBackend instance
        """
        try:
            from deepagents.backends.filesystem import FilesystemBackend
        except ImportError as e:
            raise ImportError(
                f"{LOG_PREFIX} deepagents.backends.filesystem.FilesystemBackend is required but not available. "
                f"Install deepagents: pip install deepagents. Error: {e}"
            ) from e

        user_dir = sanitize_path_component(user_id, default="default")

        if thread_id is not None and run_id is not None:
            # Unified artifact storage: each run gets its own directory
            artifacts_root = resolve_artifacts_root()
            tid = sanitize_path_component(thread_id, default="default")
            rid = sanitize_path_component(run_id, default="default")
            workspace_dir = artifacts_root / user_dir / tid / rid
        else:
            # Legacy path
            workspace_root = os.getenv("DEEPAGENTS_WORKSPACE_ROOT", "/tmp/deepagents_workspaces")
            subdir = sanitize_path_component(workspace_subdir, default="default")
            workspace_dir = Path(workspace_root) / user_dir / subdir

        try:
            workspace_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"{LOG_PREFIX} Failed to create workspace directory {workspace_dir} for node '{node_label}': {e}"
            ) from e

        try:
            backend = FilesystemBackend(
                root_dir=str(workspace_dir),
                virtual_mode=False,
            )
            logger.info(f"{LOG_PREFIX} Created FilesystemBackend for node '{node_label}': root_dir={workspace_dir}")
            return backend
        except Exception as e:
            raise RuntimeError(f"{LOG_PREFIX} Failed to create FilesystemBackend for node '{node_label}': {e}") from e
