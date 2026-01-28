"""
Container Binding Manager - Manages user-container relationships.

Ensures that each user has at most one active container at a time,
enabling container reuse across sessions.
"""

import os
import random
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from loguru import logger

from app.dynamic_agent.infra.docker import ResourceLimits, UnifiedDockerManager


@dataclass
class ContainerBindingInfo:
    """Container binding information returned from operations."""

    container_id: str
    container_name: str
    binding_id: str
    docker_api: Optional[str]
    mcp_api: Optional[str]
    reused: bool
    status: str  # 'created', 'restarted', 'active', etc.
    image: str
    command: str
    working_directory: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "container_id": self.container_id,
            "container_name": self.container_name,
            "binding_id": self.binding_id,
            "docker_api": self.docker_api,
            "mcp_api": self.mcp_api,
            "reused": self.reused,
            "status": self.status,
            "image": self.image,
            "command": self.command,
            "working_directory": self.working_directory,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContainerBindingInfo":
        """Create from dictionary."""
        return cls(
            container_id=data["container_id"],
            container_name=data["container_name"],
            binding_id=data["binding_id"],
            docker_api=data.get("docker_api"),
            mcp_api=data.get("mcp_api"),
            reused=data.get("reused", False),
            status=data.get("status", "active"),
            image=data["image"],
            command=data["command"],
            working_directory=data["working_directory"],
        )


class ContainerBindingManager:
    """
    Manages container-user-session bindings.

    Features:
    - One active container per user (default)
    - Container reuse across sessions
    - Automatic cleanup of inactive containers
    - Session switching support
    """

    def __init__(self, backend):
        """
        Initialize container binding manager.

        Args:
            backend: PostgreSQL backend instance
        """
        self.backend = backend

    async def get_or_create_container(
        self,
        user_id: str,
        session_id: str,
        docker_manager: UnifiedDockerManager,
        image: str,
        command: str,
        force_new: bool = False,
    ) -> ContainerBindingInfo:
        """
        Get existing container for user or create a new one.

        Args:
            user_id: User ID
            session_id: Current session ID
            docker_manager: Docker manager instance
            image: Container image
            command: command to start container
            force_new: Force creation of new container
            host_ip: Host IP for HTTP service (e.g., start from 8000)
            host_port: Host port for HTTP service

        Returns:
            Container info dict with binding details
        """
        from loguru import logger

        # Check for existing active container
        logger.info(f"🔍 [get_or_create_container] Checking for existing container for user {user_id}...")
        if not force_new:
            existing = await self.backend.get_active_container_for_user(user_id)
            logger.info(f"🔍 [get_or_create_container] Existing container: {existing}")
            if existing:
                # Reuse existing container
                container_id = existing["container_id"]

                # Update session binding
                await self.backend.update_container_binding_session(container_id, session_id)

                # Check if container is still running
                try:
                    container_info = docker_manager.get_container_info(container_id)
                    if container_info and container_info.get("status", "") == "running":
                        # Recalculate mcp_api URL in case IP address changed
                        # Extract port from existing mcp_api or use default
                        mcp_api = existing["mcp_api"]
                        if mcp_api:
                            # Extract port from existing URL (e.g., http://192.168.64.2:8012/sse -> 8012)
                            port_match = re.search(r":(\d+)/", mcp_api)
                            if port_match:
                                port = port_match.group(1)
                                # Extract old host from URL to check if it's a problematic IP
                                host_match = re.search(r"://([^:]+):", mcp_api)
                                old_host = host_match.group(1) if host_match else None

                                # Force use localhost if old host is not localhost/127.0.0.1
                                # This handles cases where VPN or network changes cause IP address issues
                                # if old_host and old_host not in ('localhost', '127.0.0.1'):
                                # mcp_host = 'localhost'
                                # logger.info(f"🔧 [get_or_create_container] Detected non-localhost IP ({old_host}), forcing localhost for reliability")
                                # else:

                                # Use DOCKER_HOST_IP env var if set, otherwise use localhost
                                docker_host_ip = os.environ.get("DOCKER_HOST_IP")
                                mcp_host = docker_host_ip if docker_host_ip else "localhost"

                                old_mcp_api = mcp_api
                                mcp_api = f"http://{mcp_host}:{port}/sse"
                                logger.info(
                                    f"🔧 [get_or_create_container] Recalculated mcp_api: {old_mcp_api} -> {mcp_api}"
                                )

                        return ContainerBindingInfo(
                            **{
                                "container_id": container_id,
                                "container_name": existing["container_name"],
                                "binding_id": existing["binding_id"],
                                "docker_api": existing["docker_api"],
                                "mcp_api": mcp_api,
                                "reused": True,
                                "status": "running",
                                "image": image,
                                "command": command,
                                "working_directory": os.environ["DOCKER_WORKSPACE"],
                            }
                        )
                    else:
                        # Container exists but not running, restart it
                        docker_manager.start_container(container_id)
                        # Recalculate mcp_api URL in case IP address changed
                        mcp_api = existing["mcp_api"]
                        if mcp_api:
                            # Extract port from existing URL
                            port_match = re.search(r":(\d+)/", mcp_api)
                            if port_match:
                                port = port_match.group(1)
                                # Extract old host from URL to check if it's a problematic IP
                                host_match = re.search(r"://([^:]+):", mcp_api)
                                old_host = host_match.group(1) if host_match else None

                                # Force use localhost if old host is not localhost/127.0.0.1
                                # This handles cases where VPN or network changes cause IP address issues
                                if old_host and old_host not in ("localhost", "127.0.0.1"):
                                    mcp_host = "localhost"
                                    logger.info(
                                        f"🔧 [get_or_create_container] Detected non-localhost IP ({old_host}), forcing localhost for reliability"
                                    )
                                else:
                                    # Use DOCKER_HOST_IP env var if set, otherwise use localhost
                                    docker_host_ip = os.environ.get("DOCKER_HOST_IP")
                                    mcp_host = docker_host_ip if docker_host_ip else "localhost"

                                old_mcp_api = mcp_api
                                mcp_api = f"http://{mcp_host}:{port}/sse"
                                logger.info(
                                    f"🔧 [get_or_create_container] Recalculated mcp_api: {old_mcp_api} -> {mcp_api}"
                                )

                        return ContainerBindingInfo(
                            **{
                                "container_id": container_id,
                                "container_name": existing["container_name"],
                                "binding_id": existing["binding_id"],
                                "docker_api": existing["docker_api"],
                                "mcp_api": mcp_api,
                                "reused": True,
                                "status": "restarted",
                                "image": image,
                                "command": command,
                                "working_directory": os.environ["DOCKER_WORKSPACE"],
                            }
                        )
                except Exception:
                    # Container no longer exists, deactivate binding and create new
                    await self.backend.deactivate_container_binding(container_id)

        # Deactivate all existing containers for this user
        await self.backend.deactivate_user_containers(user_id)

        # Create new container
        user_id_part = user_id[:8]
        user_id_part = re.sub(r"[^a-zA-Z0-9_.-]", "", user_id_part)
        container_name = f"pentest-{user_id_part}-{uuid.uuid4().hex[:8]}-{int(time.time() * 1000)}"

        limits = ResourceLimits.from_human_readable(
            cpu=str(os.environ.get("DOCKER_CPU_CORES", 2)),
            memory=f"{os.environ.get('DOCKER_MEM_GB', 4)}G",
            disk=f"{os.environ.get('DOCKER_DISK_GB', 20)}G",
        )

        # Create container via docker manager
        # Note: volumes are auto-configured in docker_unified_manager.create_container()
        # based on SECLENS_DEV_MODE and CTF_KNOWLEDGE_HOST_PATH env vars
        container_info = docker_manager.create_container(
            image=image,
            name=container_name,
            command=command,
            # TODO: implement real load balancing
            host_name=random.choice(list(docker_manager.hosts.keys())),
            resource_limits=limits,
            detach=True,
            auto_remove=False,
            # volumes are auto-configured in create_container based on env vars
        )

        # Create binding in database
        binding_id = str(uuid.uuid4())
        await self.backend.create_container_binding(
            binding_id=binding_id,
            user_id=user_id,
            container_id=container_info["container_id"],
            container_name=container_info["container_name"],
            image=image,
            session_id=session_id,
            mcp_api=container_info["mcp_api"],
            docker_api=container_info["docker_api"],
            metadata={"created_by_session": session_id, "force_new": force_new},
        )

        return ContainerBindingInfo.from_dict(
            {
                **container_info,
                "image": image,
                "command": command,
                "working_directory": os.environ["DOCKER_WORKSPACE"],
                "binding_id": binding_id,
                "reused": False,
                "status": "created",
            }
        )

    async def switch_session(self, container_id: str, new_session_id: str):
        """
        Switch container to a new session.

        Args:
            container_id: Container ID
            new_session_id: New session ID
        """
        await self.backend.update_container_binding_session(container_id, new_session_id)

    async def release_container(self, container_id: str, docker_manager, stop: bool = False, remove: bool = False):
        """
        Release a container (deactivate binding).

        Args:
            container_id: Container ID
            docker_manager: Docker manager instance
            stop: Stop the container
            remove: Remove the container
        """
        # Deactivate binding
        await self.backend.deactivate_container_binding(container_id)

        # Optionally stop container
        if stop:
            try:
                docker_manager.stop_container(container_id)
            except Exception as e:
                logger.warning(f"Failed to stop container {container_id}: {e}")

        # Optionally remove container
        if remove:
            try:
                docker_manager.remove_container(container_id, force=True)
                await self.backend.delete_container_binding(container_id)
            except Exception as e:
                logger.warning(f"Failed to remove container {container_id}: {e}")

    async def cleanup_user_containers(self, user_id: str, docker_manager, remove_all: bool = False):
        """
        Cleanup containers for a user.

        Args:
            user_id: User ID
            docker_manager: Docker manager instance
            remove_all: Remove all containers (not just inactive)
        """
        containers = await self.backend.list_user_containers(user_id, active_only=not remove_all)

        for container in containers:
            container_id = container["container_id"]
            try:
                docker_manager.stop_container(container_id)
                docker_manager.remove_container(container_id, force=True)
                await self.backend.delete_container_binding(container_id)
            except Exception as e:
                # Container may already be removed, still clean up DB record
                logger.info(f"Container {container_id} cleanup: {e}")
                try:
                    await self.backend.delete_container_binding(container_id)
                except Exception as db_error:
                    logger.error(f"Failed to delete container binding {container_id}: {db_error}")

    async def get_user_container(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get active container for a user.

        Args:
            user_id: User ID

        Returns:
            Container binding dict or None
        """
        result = await self.backend.get_active_container_for_user(user_id)
        return result if isinstance(result, dict) else None  # type: ignore[return-value]

    async def get_container_info(self, container_id: str) -> Optional[Dict[str, Any]]:
        """
        Get container binding info.

        Args:
            container_id: Container ID

        Returns:
            Container binding dict or None
        """
        result = await self.backend.get_container_binding(container_id)
        return result if isinstance(result, dict) else None  # type: ignore[return-value]

    async def list_user_containers(self, user_id: str, active_only: bool = True) -> List[Dict[str, Any]]:
        """
        List all containers for a user.

        Args:
            user_id: User ID
            active_only: Only return active containers

        Returns:
            List of container binding dicts
        """
        result = await self.backend.list_user_containers(user_id, active_only)
        return result if isinstance(result, list) else []  # type: ignore[return-value]

    async def update_container_status(self, container_id: str, status: str):
        """
        Update container status.

        Args:
            container_id: Container ID
            status: New status (e.g., 'running', 'stopped', 'error')
        """
        await self.backend.update_container_binding_status(container_id, status)
