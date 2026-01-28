"""Backend factory for DeepAgents graph builder.

This module provides a factory pattern for creating different types of backends
(filesystem, docker) based on node configuration. This separation of concerns
improves maintainability and testability.
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

# Default configuration values
DEFAULT_DOCKER_IMAGE = "python:3.12-slim"
DEFAULT_MEMORY_LIMIT = "512m"
DEFAULT_CPU_QUOTA = 50000
DEFAULT_NETWORK_MODE = "none"
DEFAULT_WORKING_DIR = "/workspace"
DEFAULT_AUTO_REMOVE = True
DEFAULT_MAX_OUTPUT_SIZE = 100000
DEFAULT_COMMAND_TIMEOUT = 30

# Backend type constants
BACKEND_TYPE_FILESYSTEM = "filesystem"
BACKEND_TYPE_DOCKER = "docker"


class BackendFactory:
    """Factory for creating backend instances based on configuration."""

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
    def create_backend(
        node: "GraphNode",
        user_id: Optional[str] = None,
        workspace_subdir: Optional[str] = None,
    ) -> Any:
        """Create backend for node based on backend_type configuration.

        Supports two backend types:
        - 'filesystem': Uses deepAgents' native FilesystemBackend
        - 'docker': Uses PydanticSandboxAdapter (Docker sandbox)

        Args:
            node: GraphNode to extract configuration from
            user_id: User ID for workspace directory isolation
            workspace_subdir: Custom subdirectory name (defaults to graph name)

        Returns:
            Backend instance (FilesystemBackend or PydanticSandboxAdapter)

        Raises:
            ImportError: If required backend library is not available
            RuntimeError: If backend creation fails
            ValueError: If backend_type is unsupported
        """
        data = node.data or {}
        config = data.get("config", {})
        backend_type = config.get("backend_type", BACKEND_TYPE_FILESYSTEM)
        node_label = data.get("label", "unknown")

        if backend_type == BACKEND_TYPE_DOCKER:
            return BackendFactory._create_docker_backend(config, node_label)
        elif backend_type == BACKEND_TYPE_FILESYSTEM:
            return BackendFactory._create_filesystem_backend(
                node, node_label, user_id=user_id, workspace_subdir=workspace_subdir
            )
        else:
            raise ValueError(
                f"{LOG_PREFIX} Unsupported backend_type '{backend_type}' for node '{node_label}'. "
                "Supported types: 'filesystem', 'docker'"
            )

    @staticmethod
    def _create_docker_backend(config: dict, node_label: str) -> Any:
        """Create Docker backend using PydanticSandboxAdapter.

        Args:
            config: Node configuration dictionary
            node_label: Node label for logging

        Returns:
            PydanticSandboxAdapter instance

        Raises:
            ImportError: If pydantic-ai-backend[docker] is not available
            RuntimeError: If backend creation fails
        """
        try:
            from app.core.agent.backends.pydantic_adapter import (
                PYDANTIC_BACKEND_AVAILABLE,
                PydanticSandboxAdapter,
            )
        except ImportError as e:
            logger.warning(
                f"{LOG_PREFIX} Failed to import PydanticSandboxAdapter for node '{node_label}': {e}. "
                "Falling back to FilesystemBackend"
            )
            raise ImportError(
                f"{LOG_PREFIX} PydanticSandboxAdapter not available. "
                "Install with: pip install pydantic-ai-backend[docker]"
            ) from e

        if not PYDANTIC_BACKEND_AVAILABLE:
            logger.warning(
                f"{LOG_PREFIX} PydanticSandboxAdapter not available for node '{node_label}'. "
                "Falling back to FilesystemBackend. "
                "Install with: pip install pydantic-ai-backend[docker]"
            )
            raise ImportError(
                f"{LOG_PREFIX} PydanticSandboxAdapter not available. "
                "Install with: pip install pydantic-ai-backend[docker]"
            )

        # Read docker_config from node config
        docker_config = config.get("docker_config", {})

        try:
            backend = PydanticSandboxAdapter(
                image=docker_config.get("image", DEFAULT_DOCKER_IMAGE),
                memory_limit=docker_config.get("memory_limit", DEFAULT_MEMORY_LIMIT),
                cpu_quota=docker_config.get("cpu_quota", DEFAULT_CPU_QUOTA),
                network_mode=docker_config.get("network_mode", DEFAULT_NETWORK_MODE),
                working_dir=docker_config.get("working_dir", DEFAULT_WORKING_DIR),
                auto_remove=docker_config.get("auto_remove", DEFAULT_AUTO_REMOVE),
                max_output_size=docker_config.get("max_output_size", DEFAULT_MAX_OUTPUT_SIZE),
                command_timeout=docker_config.get("command_timeout", DEFAULT_COMMAND_TIMEOUT),
            )
            logger.info(
                f"{LOG_PREFIX} Created PydanticSandboxAdapter (Docker) for node "
                f"'{node_label}': image={docker_config.get('image', DEFAULT_DOCKER_IMAGE)}"
            )
            return backend
        except Exception as e:
            logger.error(f"{LOG_PREFIX} Failed to create PydanticSandboxAdapter for node '{node_label}': {e}")
            raise RuntimeError(f"{LOG_PREFIX} Failed to create Docker backend for node '{node_label}': {e}") from e

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

    @staticmethod
    def create_backend_with_fallback(
        node: "GraphNode",
        user_id: Optional[str] = None,
        workspace_subdir: Optional[str] = None,
    ) -> Any:
        """Create backend with automatic fallback to filesystem on error.

        This method attempts to create the configured backend type, but falls back
        to filesystem backend if the configured type fails (e.g., Docker not available).

        Args:
            node: GraphNode to extract configuration from
            user_id: User ID for workspace directory isolation
            workspace_subdir: Custom subdirectory name (defaults to graph name)

        Returns:
            Backend instance (always succeeds, falls back to FilesystemBackend if needed)
        """
        data = node.data or {}
        config = data.get("config", {})
        backend_type = config.get("backend_type", BACKEND_TYPE_FILESYSTEM)
        node_label = data.get("label", "unknown")

        # If already filesystem, create directly
        if backend_type == BACKEND_TYPE_FILESYSTEM:
            return BackendFactory._create_filesystem_backend(
                node, node_label, user_id=user_id, workspace_subdir=workspace_subdir
            )

        # Try to create configured backend (docker)
        try:
            return BackendFactory._create_docker_backend(config, node_label)
        except (ImportError, RuntimeError) as e:
            logger.warning(
                f"{LOG_PREFIX} Failed to create {backend_type} backend for node '{node_label}': {e}. "
                "Falling back to FilesystemBackend"
            )
            # Fallback to filesystem backend
            return BackendFactory._create_filesystem_backend(
                node, node_label, user_id=user_id, workspace_subdir=workspace_subdir
            )
