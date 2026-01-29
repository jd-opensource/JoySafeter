"""
Docker container management system
Supports dynamic creation, execution, resource limits and monitoring
"""

import os
import shutil
from typing import Any, Dict, List, Optional, Tuple

import docker
from docker.errors import ImageNotFound
from docker.models.containers import Container
from loguru import logger

from app.dynamic_agent.core.constants import DOCKER_RUN_CAPS, DOCKER_RUN_GROUP, DOCKER_RUN_USER

from .exceptions import (
    ContainerExecutionError,
    ContainerNotFoundError,
    ContainerStateError,
    DockerConnectionError,
)
from .resource_limiter import ResourceLimits
from .resource_monitor import ResourceMetrics, ResourceMonitor


class ContainerInfo:
    """Container information"""

    def __init__(self, container: Container):
        self.container = container
        self.id = container.id
        self.short_id = container.short_id
        self.name = container.name
        self.image = container.image.tags[0] if container.image.tags else "unknown"
        self.status = container.status
        self.created = container.attrs.get("Created")
        self.started = container.attrs.get("State", {}).get("StartedAt")

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "short_id": self.short_id,
            "name": self.name,
            "image": self.image,
            "status": self.status,
            "created": self.created,
            "started": self.started,
        }


class DockerManager:
    """
    Docker container manager

    Supports:
    - Dynamic container creation
    - Container command execution
    - Resource limits (CPU, memory, disk, process count)
    - Resource monitoring
    - Container lifecycle management

    Example:
        >>> manager = DockerManager()
        >>> container = manager.create_container(
        ...     image='ubuntu:20.04',
        ...     command='echo hello',
        ...     resource_limits=ResourceLimits.from_human_readable(
        ...         cpu='1',
        ...         memory='512M'
        ...     )
        ... )
        >>> output = manager.execute_command(container.id, 'ls -la')
        >>> metrics = manager.monitor_resources(container.id, duration=10)
        >>> manager.stop_container(container.id)
    """

    def _ensure_client(self) -> docker.DockerClient:
        """Ensure client is initialized, raise error if not."""
        if self.client is None:
            raise DockerConnectionError("Docker client is not initialized")
        return self.client

    def __init__(self, base_url: Optional[str] = None):
        """
        Initialize Docker manager

        Args:
            base_url: Docker daemon URL, defaults to Unix socket

        Raises:
            DockerConnectionError: Cannot connect to Docker daemon
        """
        self.client = None
        try:
            if base_url:
                self.client = docker.DockerClient(base_url=base_url)
            else:
                try:
                    self.client = docker.from_env()
                except Exception as e:
                    logger.warning("Failed to connect to Docker daemon: %s, try to use colima", e)

                    # in case colima is installed
                    if shutil.which("colima"):
                        if DockerManager.initialize_colima():
                            try:
                                self.client = docker.from_env()
                            except Exception as colima_error:
                                logger.error(
                                    f"Failed to connect to Docker even after Colima initialization: {colima_error}"
                                )
                                self.client = None
                    else:
                        logger.warning("Colima not found, cannot initialize Docker connection")

            # Test connection - only if client was successfully initialized
            if self.client is None:
                raise DockerConnectionError(
                    "Docker client not initialized. Cannot connect to Docker daemon. "
                    "If running in a container, you may need to mount Docker socket: "
                    "-v /var/run/docker.sock:/var/run/docker.sock"
                )

            self.client.ping()
            logger.info("Docker connection successful")
        except DockerConnectionError:
            raise
        except Exception as e:
            raise DockerConnectionError(f"Cannot connect to Docker daemon: {e}")

        self.monitor = ResourceMonitor(self.client)
        self.containers: Dict[str, ContainerInfo] = {}

    @classmethod
    def initialize_colima(cls, auto_start: bool = True) -> bool:
        """
        Initialize Colima and Docker environment

        Returns:
            True if successful, False otherwise
        """
        if not shutil.which("colima"):
            logger.error("Colima not found")
            return False

        from . import ColimaHelper

        logger.debug("\n" + "=" * 70)
        logger.debug("Initializing Colima Docker Environment")
        logger.debug("=" * 70 + "\n")

        # Step 1: Check Colima installation
        logger.debug("📋 Step 1: Checking Colima installation...")
        if not ColimaHelper.is_colima_installed():
            logger.debug("❌ Colima not installed")
            logger.debug("   Install with: brew install colima")
            return False
        logger.debug("✅ Colima is installed\n")

        # Step 2: Check/Start Colima
        logger.debug("📋 Step 2: Checking Colima status...")
        if not ColimaHelper.is_colima_running():
            if not auto_start:
                logger.debug("❌ Colima is not running")
                logger.debug("   Start with: colima start")
                return False

            logger.debug("⏳ Colima not running, starting...")
            success, msg = ColimaHelper.start_colima(cpu=4, memory=8, disk=100)
            if not success:
                logger.debug(f"❌ {msg}")
                return False
            logger.debug(f"✅ {msg}\n")
        else:
            logger.debug("✅ Colima is running\n")

        # Step 3: Setup Docker environment
        logger.debug("📋 Step 3: Setting up Docker environment...")
        success, msg = ColimaHelper.setup_environment()
        if not success:
            logger.debug(f"❌ {msg}")
            return False
        logger.debug(f"✅ {msg}\n")

        # Step 4: Print status
        logger.debug("📋 Step 4: Environment status:")
        ColimaHelper.print_status()

        return True

    def create_container(
        self,
        image: str,
        command: Optional[str] = None,
        name: Optional[str] = None,
        resource_limits: Optional[ResourceLimits] = None,
        environment: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        ports: Optional[Dict[str, int]] = None,
        network_mode: str = "bridge",  # Use bridge with extra_hosts for macOS/Colima
        detach: bool = True,
        auto_remove: bool = False,
        **kwargs,
    ) -> ContainerInfo:
        """
        Create Docker container

        Args:
            image: Image name (e.g., 'ubuntu:20.04')
            command: Start command (e.g., 'bash -c "echo hello"')
            name: Container name
            resource_limits: Resource limit configuration
            environment: Environment variables dictionary
            volumes: Volume mount configuration
            ports: Port mapping configuration
            network_mode: Network mode (bridge/host/container/none)
            detach: Whether to run in background
            auto_remove: Whether to auto-remove when stopped
            **kwargs: Other Docker API parameters

        Returns:
            ContainerInfo: Container information

        Raises:
            ContainerCreationError: Container creation failed

        Example:
            >>> limits = ResourceLimits.from_human_readable(
            ...     cpu='1',
            ...     memory='512M',
            ...     disk='10G'
            ... )
            >>> container = manager.create_container(
            ...     image='ubuntu:20.04',
            ...     command='sleep 3600',
            ...     name='test-container',
            ...     resource_limits=limits,
            ...     environment={'DEBUG': 'true'},
            ...     detach=True
            ... )
        """
        try:
            # Check if image exists, pull if not
            client = self._ensure_client()
            try:
                client.images.get(image)
            except ImageNotFound:
                logger.info(f"Image {image} not found, pulling...")
                client.images.pull(image)

            # Build container parameters
            container_kwargs: Dict[str, Any] = {
                "image": image,
                "command": command,
                "detach": detach,
                "auto_remove": auto_remove,
                "network_mode": network_mode,
            }

            if name:
                container_kwargs["name"] = name

            if environment:
                container_kwargs["environment"] = environment

            if volumes:
                container_kwargs["volumes"] = volumes

            # host network mode is incompatible with port bindings
            if ports and network_mode != "host":
                container_kwargs["ports"] = ports

            # macOS/Colima: Add extra_hosts to allow container to access host network
            # This maps 'host.docker.internal' to the host gateway IP
            container_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}

            #  user=f"{uid}:{gid}"
            container_kwargs["user"] = f"{os.environ[DOCKER_RUN_USER]}:{os.environ[DOCKER_RUN_GROUP]}"
            container_kwargs["cap_add"] = DOCKER_RUN_CAPS
            # Add resource limits
            if resource_limits:
                container_kwargs.update(resource_limits.to_docker_kwargs())

            # Add other parameters
            container_kwargs.update(kwargs)

            # Create container
            client = self._ensure_client()  # Already ensured above
            container = client.containers.create(**container_kwargs)

            try:
                # Start container
                container.start()
            except Exception as e:
                try:
                    container.remove(force=True)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup failed container: {cleanup_error}")
                raise e

            # Save container information
            info = ContainerInfo(container)
            self.containers[container.id] = info

            logger.info(f"Container created successfully: {info.name} ({info.short_id})")
            return info

        except Exception as e:
            # raise ContainerCreationError(f"Container creation failed: {e}")
            raise e

    def execute_command(
        self,
        container_id: str,
        command: str,
        timeout: Optional[int] = None,
        privileged: bool = False,
    ) -> Tuple[int, str, str]:
        """
        Execute command in container

        Args:
            container_id: Container ID or name
            command: Command to execute
            timeout: Execution timeout in seconds
            privileged: Whether to execute in privileged mode

        Returns:
            Tuple[int, str, str]: (exit_code, stdout, stderr)

        Raises:
            ContainerNotFoundError: Container not found
            ContainerExecutionError: Command execution failed

        Example:
            >>> exit_code, stdout, stderr = manager.execute_command(
            ...     container_id='abc123',
            ...     command='ls -la /tmp',
            ...     timeout=30
            ... )
            >>> print(f"Exit code: {exit_code}")
            >>> print(f"Output: {stdout}")
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)
        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")

        try:
            # Check container status
            container.reload()
            if container.status != "running":
                raise ContainerStateError(f"Container not running: {container.status}")

            # Execute command
            result = container.exec_run(
                cmd=command,
                stdout=True,
                stderr=True,
                privileged=privileged,
            )

            exit_code = result.exit_code
            stdout = result.output.decode("utf-8", errors="ignore") if result.output else ""
            stderr = ""  # Docker exec_run mixes stderr into stdout

            logger.debug(f"Command execution completed: {command} (exit_code={exit_code})")
            return exit_code, stdout, stderr

        except docker.errors.APIError as e:
            raise ContainerExecutionError(f"Command execution failed: {e}")

    def get_container_info(self, container_id: str) -> ContainerInfo:
        """
        Get container information

        Args:
            container_id: Container ID or name

        Returns:
            ContainerInfo: Container information

        Raises:
            ContainerNotFoundError: Container not found
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)
            return ContainerInfo(container)
        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")

    def list_containers(self, all: bool = False) -> List[ContainerInfo]:
        """
        List containers

        Args:
            all: Whether to list all containers (including stopped)

        Returns:
            List[ContainerInfo]: List of container information
        """
        client = self._ensure_client()
        containers = client.containers.list(all=all)
        return [ContainerInfo(c) for c in containers]

    def stop_container(
        self,
        container_id: str,
        timeout: int = 10,
        force: bool = False,
    ) -> None:
        """
        Stop container

        Args:
            container_id: Container ID or name
            timeout: Stop timeout in seconds
            force: Whether to force stop (SIGKILL)

        Raises:
            ContainerNotFoundError: Container not found
            ContainerExecutionError: Stop failed
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)

            if force:
                container.kill()
                logger.info(f"Container force stopped: {container.name}")
            else:
                container.stop(timeout=timeout)
                logger.info(f"Container stopped: {container.name}")

        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")
        except docker.errors.APIError as e:
            raise ContainerExecutionError(f"Stop container failed: {e}")

    def remove_container(
        self,
        container_id: str,
        force: bool = False,
        volumes: bool = False,
    ) -> None:
        """
        Remove container

        Args:
            container_id: Container ID or name
            force: Whether to force remove (stop first then remove)
            volumes: Whether to remove associated volumes

        Raises:
            ContainerNotFoundError: Container not found
            ContainerExecutionError: Remove failed
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)
            container.remove(force=force, v=volumes)

            # Remove from cache
            self.containers.pop(container.id, None)

            logger.info(f"Container removed: {container.name}")

        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")
        except docker.errors.APIError as e:
            raise ContainerExecutionError(f"Remove container failed: {e}")

    def restart_container(
        self,
        container_id: str,
        timeout: int = 10,
    ) -> None:
        """
        Restart container

        Args:
            container_id: Container ID or name
            timeout: Restart timeout in seconds

        Raises:
            ContainerNotFoundError: Container not found
            ContainerExecutionError: Restart failed
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)
            container.restart(timeout=timeout)
            logger.info(f"Container restarted: {container.name}")

        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")
        except docker.errors.APIError as e:
            raise ContainerExecutionError(f"Restart container failed: {e}")

    def pause_container(self, container_id: str) -> None:
        """
        Pause container

        Args:
            container_id: Container ID or name

        Raises:
            ContainerNotFoundError: Container not found
            ContainerExecutionError: Pause failed
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)
            container.pause()
            logger.info(f"Container paused: {container.name}")

        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")
        except docker.errors.APIError as e:
            raise ContainerExecutionError(f"Pause container failed: {e}")

    def unpause_container(self, container_id: str) -> None:
        """
        Resume container

        Args:
            container_id: Container ID or name

        Raises:
            ContainerNotFoundError: Container not found
            ContainerExecutionError: Resume failed
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)
            container.unpause()
            logger.info(f"Container resumed: {container.name}")

        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")
        except docker.errors.APIError as e:
            raise ContainerExecutionError(f"Resume container failed: {e}")

    def monitor_resources(
        self,
        container_id: str,
        duration: int = 60,
        interval: float = 1.0,
    ) -> ResourceMetrics:
        """
        Monitor container resource usage

        Args:
            container_id: Container ID
            duration: Monitoring duration in seconds
            interval: Monitoring interval in seconds

        Returns:
            ResourceMetrics: Resource metrics

        Raises:
            ContainerNotFoundError: Container not found

        Example:
            >>> metrics = manager.monitor_resources(
            ...     container_id='abc123',
            ...     duration=30,
            ...     interval=1
            ... )
            >>> print(f"Average CPU: {metrics.get_avg_cpu()}%")
            >>> print(f"Max memory: {metrics.get_max_memory()} bytes")
            >>> print(metrics.to_dict())
        """
        return self.monitor.collect_metrics(
            container_id=container_id,
            duration=duration,
            interval=interval,
        )

    def get_container_logs(
        self,
        container_id: str,
        tail: int = 100,
        follow: bool = False,
    ) -> str:
        """
        Get container logs

        Args:
            container_id: Container ID
            tail: Get last N lines of logs
            follow: Whether to stream output

        Returns:
            str: Container logs

        Raises:
            ContainerNotFoundError: Container not found
        """
        try:
            client = self._ensure_client()
            container = client.containers.get(container_id)
            logs = container.logs(tail=tail, follow=follow)
            decoded = logs.decode("utf-8", errors="ignore")
            return str(decoded)
        except docker.errors.NotFound:
            raise ContainerNotFoundError(f"Container not found: {container_id}")

    def cleanup(self):
        """Clean up resources"""
        self.containers.clear()
        logger.info("Docker manager cleaned up")
