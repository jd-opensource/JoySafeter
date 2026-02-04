"""Backend factory for DeepAgents graph builder.

This module provides filesystem backend creation only.
Docker backends are managed centrally by DeepAgentsGraphBuilder.
"""

import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

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
    ) -> Any:
        """Create Filesystem backend using deepAgents FilesystemBackend.

        目录结构: /tmp/deepagents_workspaces/{sanitized_user_id}/{sanitized_workspace_subdir}/{node_id}

        Args:
            node: GraphNode to extract node ID from
            node_label: Node label for logging
            user_id: User ID for workspace directory isolation (will be sanitized)
            workspace_subdir: Custom subdirectory name (will be sanitized, defaults to "default")

        Returns:
            FilesystemBackend instance

        Raises:
            ImportError: If deepagents.backends.filesystem is not available
            RuntimeError: If backend creation fails
        """
        try:
            from deepagents.backends.filesystem import FilesystemBackend
        except ImportError as e:
            raise ImportError(
                f"{LOG_PREFIX} deepagents.backends.filesystem.FilesystemBackend is required but not available. "
                f"Install deepagents: pip install deepagents. Error: {e}"
            ) from e

        # 获取基础路径
        workspace_root = os.getenv("DEEPAGENTS_WORKSPACE_ROOT", "/tmp/deepagents_workspaces")

        # 安全清理所有路径组件
        user_dir = sanitize_path_component(user_id, default="default")
        subdir = sanitize_path_component(workspace_subdir, default="default")

        # 构建完整路径: {workspace_root}/{user_id}/{workspace_subdir}/
        workspace_dir = Path(workspace_root) / user_dir / subdir

        try:
            # 先删除目录（如果存在），然后重新创建
            if workspace_dir.exists():
                shutil.rmtree(workspace_dir)
                logger.debug(f"{LOG_PREFIX} Removed existing workspace directory: {workspace_dir}")

            workspace_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise RuntimeError(
                f"{LOG_PREFIX} Failed to create workspace directory {workspace_dir} for node '{node_label}': {e}"
            ) from e

        try:
            backend = FilesystemBackend(
                root_dir=str(workspace_dir),
                virtual_mode=False,  # Disable path mapping, use relative paths within root_dir
            )
            logger.info(
                f"{LOG_PREFIX} Created FilesystemBackend for node "
                f"'{node_label}': root_dir={workspace_dir} (user_id={user_dir}, subdir={subdir}"
            )
            return backend
        except Exception as e:
            raise RuntimeError(f"{LOG_PREFIX} Failed to create FilesystemBackend for node '{node_label}': {e}") from e
