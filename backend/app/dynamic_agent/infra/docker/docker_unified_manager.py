"""
Unified Docker Manager - Integrates local and remote Docker management

Provides a single interface for managing containers on both local and remote Docker daemons.
Automatically routes operations to the appropriate backend (local or remote).
"""

import os
from dataclasses import dataclass
from time import sleep
from typing import Any, Dict, List, Optional, Tuple

from docker.errors import APIError
from loguru import logger

from app.dynamic_agent.core.constants import (
    AGENT_CONTAINER_PATH,
    AGENT_HOST_PATH,
    CTF_KNOWLEDGE_CONTAINER_PATH,
    CTF_KNOWLEDGE_HOST_PATH,
    DEV_MODE_ENV,
    DOCKER_HOST_IP,
    ENGINE_CONTAINER_PATH,
    ENGINE_HOST_PATH,
    LOCALHOST,
)

from .docker_manager import DockerManager
from .docker_remote_api import DockerRemoteAPIManager, RemoteDockerHost
from .exceptions import (
    ContainerCreationError,
    ContainerExecutionError,
    ContainerStateError,
)
from .resource_limiter import ResourceLimits


@dataclass
class HostConfig:
    """Host configuration for unified manager"""

    host_name: str
    is_local: bool = True
    remote_host: Optional[RemoteDockerHost] = None


class UnifiedDockerManager:
    """
    Unified Docker Manager for local and remote container management.

    Provides a single interface for managing containers on both local and remote
    Docker daemons. Automatically routes operations to the appropriate backend.

    Features:
    - Unified API for local and remote operations
    - Automatic host detection and routing
    - Support for multiple remote hosts
    - Seamless fallback between local and remote
    - Comprehensive error handling

    Example:
        >>> # Initialize with local Docker
        >>> manager = UnifiedDockerManager()

        >>> # Add remote hosts
        >>> tls = TLSConfig(
        ...     client_cert='~/.docker/client.pem',
        ...     client_key='~/.docker/client-key.pem',
        ...     ca_cert='~/.docker/ca.pem'
        ... )
        >>> remote_host = RemoteDockerHost(
        ...     host='192.168.1.10',
        ...     port=2376,
        ...     tls_config=tls,
        ...     name='production-server'
        ... )
        >>> manager.add_remote_host(remote_host)

        >>> # Create container on local host
        >>> container = manager.create_container(
        ...     image='ubuntu:20.04',
        ...     command='sleep 3600'
        ... )

        >>> # Create container on remote host
        >>> remote_container = manager.create_container(
        ...     image='ubuntu:20.04',
        ...     command='sleep 3600',
        ...     host_name='production-server'
        ... )

        >>> # Execute command (auto-routes to correct host)
        >>> exit_code, stdout, stderr = manager.execute_command(
        ...     container_id=container.id,
        ...     command='whoami'
        ... )
    """

    def __init__(self, local_base_url: Optional[str] = None):
        """
        Initialize Unified Docker Manager.

        Args:
            local_base_url: Optional base URL for local Docker daemon
        """
        self.current_host_ip = os.environ.get(DOCKER_HOST_IP, LOCALHOST)

        # Initialize local Docker manager
        self.local_manager = DockerManager(base_url=local_base_url)
        logger.info("Local Docker manager initialized")

        # Initialize remote API manager
        self.remote_manager = DockerRemoteAPIManager()
        logger.info("Remote Docker API manager initialized")

        # Track host configurations
        self.hosts: Dict[str, HostConfig] = {}

        # Add local host
        # if self.current_host_ip and self.current_host_ip not in [LOCALHOST, '127.0.0.1']:
        #     host_conf = RemoteDockerHost(self.current_host_ip, int(os.environ.get(DOCKER_HOST_PORT, 2376)))
        #     self.hosts[self.current_host_ip] = HostConfig(
        #         host_name=self.current_host_ip,
        #         is_local=False,
        #         remote_host=host_conf
        #     )
        #     self.remote_manager.add_host(RemoteDockerHost(host_conf.host, host_conf.port))
        # else:
        #     self.hosts[LOCALHOST] = HostConfig(
        #         host_name=LOCALHOST,
        #         is_local=True
        #     )

        self.hosts[LOCALHOST] = HostConfig(host_name=LOCALHOST, is_local=True)

        logger.info("Unified Docker Manager initialized")

    # todo load from config
    def add_remote_host(self, host: RemoteDockerHost) -> bool:
        """
        Add a remote Docker host.

        Args:
            host: Remote Docker host configuration

        Returns:
            True if connection successful, False otherwise
        """
        if not self.remote_manager.add_host(host):
            return False

        host_name = host.name or host.host
        self.hosts[host_name] = HostConfig(host_name=host_name, is_local=False, remote_host=host)

        logger.info(f"Remote host added: {host_name}")
        return True

    def remove_remote_host(self, host_name: str) -> bool:
        """
        Remove a remote Docker host.

        Args:
            host_name: Host name or identifier

        Returns:
            True if successful, False otherwise
        """
        if host_name not in self.hosts:
            logger.warning(f"Host not found: {host_name}")
            return False

        if self.remote_manager.remove_host(host_name):
            del self.hosts[host_name]
            logger.info(f"Remote host removed: {host_name}")
            return True

        return False

    def list_hosts(self) -> List[HostConfig]:
        """
        List all available hosts.

        Returns:
            List of host configurations
        """
        return list(self.hosts.values())

    def create_container(
        self,
        image: str,
        command: Optional[str] = None,
        name: Optional[str] = None,
        host_name: Optional[str] = None,
        resource_limits: Optional[ResourceLimits] = None,
        environment: Optional[Dict[str, str]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        # ports: Optional[Dict[str, int]] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Create a container on specified host.

        Args:
            image: Container image
            command: Container command
            name: Container name
            host_name: Target host (defaults to LOCALHOST)
            **kwargs: Additional parameters

        Returns:
            Container information dict

        Raises:
            ContainerCreationError: If creation fails
        """
        # if self.current_host_ip and self.current_host_ip not in [LOCALHOST, '127.0.0.1']:
        #     host_config = self.hosts[self.current_host_ip]
        # else:
        #     host_config = self.hosts[LOCALHOST]

        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            raise ValueError(f"Host not found: {host_name}")

        host_config = self.hosts[host_name]

        # Auto-mount volumes
        if volumes is None:
            volumes = {}

        # Get backend root for default paths (backend/ directory containing engine/ and agent/)
        # __file__ is docker_unified_manager.py in agent/runtime/docker/
        # Go up 3 levels to get to backend/
        backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

        # Check if dev mode is enabled
        dev_mode_value = os.environ.get(DEV_MODE_ENV, "")
        dev_mode = dev_mode_value.lower() in ("1", "true", "yes")
        logger.info(f"🔍 DEV_MODE check: env={DEV_MODE_ENV}, value='{dev_mode_value}', enabled={dev_mode}")

        if dev_mode:
            logger.info("🔧 Dev mode enabled - mounting source code directories")

            # Mount engine directory
            engine_host = os.environ.get(ENGINE_HOST_PATH)
            if not engine_host:
                engine_host = os.path.join(backend_root, "dynamic_engine")
            if os.path.exists(engine_host):
                volumes[engine_host] = {"bind": ENGINE_CONTAINER_PATH, "mode": "rw"}
                logger.info(f"📦 Mounting engine: {engine_host} -> {ENGINE_CONTAINER_PATH}")
            else:
                logger.warning(f"⚠️ Engine path not found: {engine_host}")

            # Mount agent directory
            agent_host = os.environ.get(AGENT_HOST_PATH)
            if not agent_host:
                agent_host = os.path.join(backend_root, "app")
            if os.path.exists(agent_host):
                volumes[agent_host] = {"bind": AGENT_CONTAINER_PATH, "mode": "rw"}
                logger.info(f"📦 Mounting agent: {agent_host} -> {AGENT_CONTAINER_PATH}")
            else:
                logger.warning(f"⚠️ Agent path not found: {agent_host}")

            # Always mount CTF knowledge base (read-only)
            ctf_knowledge_host = os.environ.get(CTF_KNOWLEDGE_HOST_PATH)
            if not ctf_knowledge_host:
                ctf_knowledge_host = os.path.join(backend_root, "dynamic_engine", "handlers", "knowledge", "ctf")

            if os.path.exists(ctf_knowledge_host):
                volumes[ctf_knowledge_host] = {"bind": CTF_KNOWLEDGE_CONTAINER_PATH, "mode": "ro"}
                logger.info(f"📚 Mounting CTF knowledge: {ctf_knowledge_host} -> {CTF_KNOWLEDGE_CONTAINER_PATH}")

            # Log all volumes being mounted
            if volumes:
                logger.info(f"📦 Total volumes to mount: {len(volumes)}")
                for host_path, mount_config in volumes.items():
                    logger.info(f"   - {host_path} -> {mount_config}")

        native_port = int(os.getenv("ENGINE_NATIVE_PORT", "9100"))
        for i in range(200):
            ports: Dict[str, int] = {"8000": native_port}
            try:
                if host_config.is_local:
                    logger.info(f"Creating container on local host: {image}")
                    logger.info(f"📦 Volumes being passed to create_container: {volumes}")
                    container = self.local_manager.create_container(
                        image=image,
                        command=command,
                        name=name,
                        resource_limits=resource_limits,
                        environment=environment,
                        volumes=volumes,
                        ports=ports,
                        **kwargs,
                    )
                    # wait for container is availabel
                    sleep(10)
                    # Use DOCKER_HOST_IP env var if set (for Colima/Lima setups where port forwarding is broken)
                    mcp_host = os.environ.get("DOCKER_HOST_IP", "localhost")
                    return {
                        "container_id": container.id,
                        "container_short_id": container.short_id,
                        "container_name": container.name,
                        "host_name": LOCALHOST,
                        "is_local": True,
                        "docker_api": None,
                        "mcp_api": f"http://{mcp_host}:{native_port}/sse",
                    }
                else:
                    logger.info(f"Creating container on remote host: {host_name}")
                    result = self.remote_manager.create_container(
                        host_name=host_name,
                        image=image,
                        command=command,
                        name=name,
                        resource_limits=resource_limits,
                        environment=environment,
                        volumes=volumes,
                        ports=ports,
                        **kwargs,
                    )
                    if result:
                        # wait for container is availabel
                        sleep(10)
                        result["is_local"] = False
                        if host_config.remote_host:
                            result.update(
                                {
                                    "docker_api": None,
                                    "mcp_api": f"http://{host_config.remote_host.host}:{native_port}/sse",
                                }
                            )
                        return result
                    # raise ContainerCreationError(f"Failed to create container on {host_name}")

            # 409
            # 'Conflict. The container name "/pentest-user_123-2e5d995f" is already in use by container "5094943bc91be274726c70de7f54ad1ee0eb14573d7d80ef4f32675da27a5700". You have to remove (or rename) that container to be able to reuse that name.'
            except Exception as e:
                logger.warning(f"Failed to create container: {e}")
                # 500 Server Error for http+docker://localhost/v1.51/containers/5094943bc91be274726c70de7f54ad1ee0eb14573d7d80ef4f32675da27a5700/start: Internal Server Error ("failed to set up container networking: driver failed programming external connectivity on endpoint pentest-user_123-2e5d995f (1c16361d8655ebd2750a00187f49078276ac982a8910147f7449d2893b62aa68): Bind for 0.0.0.0:8000 failed: port is already allocated")

                if isinstance(e, APIError) and e.status_code == 500 and "port is already allocated" in e.explanation:
                    logger.info(f"Port {native_port} is already allocated")
                    native_port += 1
                    continue
                else:
                    raise e

        # If we exhausted all retries, raise an error
        raise ContainerCreationError("Failed to create container after 200 attempts")

    def execute_command(
        self, container_id: str, command: str, host_name: Optional[str] = None, timeout: Optional[int] = None, **kwargs
    ) -> Tuple[int, str, str]:
        """
        Execute command in container.

        Args:
            container_id: Container ID
            command: Command to execute
            host_name: Target host (defaults to LOCALHOST)
            timeout: Execution timeout
            **kwargs: Additional parameters

        Returns:
            Tuple of (exit_code, stdout, stderr)

        Raises:
            ContainerExecutionError: If execution fails
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            raise ValueError(f"Host not found: {host_name}")

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.debug(f"Executing command on local container: {container_id}")
                return self.local_manager.execute_command(
                    container_id=container_id, command=command, timeout=timeout, **kwargs
                )
            else:
                logger.debug(f"Executing command on remote container: {container_id}")
                result = self.remote_manager.execute_command(
                    host_name=host_name, container_id=container_id, command=command, timeout=timeout or 300
                )
                if result:
                    return result
                raise ContainerExecutionError(f"Failed to execute command on {host_name}")

        except Exception as e:
            logger.error(f"Command execution failed on {host_name}: {e}")
            raise ContainerExecutionError(f"Failed to execute command: {e}")

    def stop_container(
        self, container_id: str, host_name: Optional[str] = None, timeout: int = 10, force: bool = False
    ) -> None:
        """
        Stop a container.

        Args:
            container_id: Container ID
            host_name: Target host (defaults to LOCALHOST)
            timeout: Stop timeout
            force: Force stop

        Raises:
            ContainerStateError: If stop fails
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            raise ValueError(f"Host not found: {host_name}")

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.info(f"Stopping local container: {container_id}")
                self.local_manager.stop_container(container_id=container_id, timeout=timeout, force=force)
            else:
                logger.info(f"Stopping remote container: {container_id}")
                self.remote_manager.stop_container(host_name=host_name, container_id=container_id)

        except Exception as e:
            logger.error(f"Failed to stop container on {host_name}: {e}")
            raise ContainerStateError(f"Failed to stop container: {e}")

    def start_container(self, container_id: str, host_name: Optional[str] = None) -> None:
        """
        Start a stopped container.

        Args:
            container_id: Container ID
            host_name: Target host (defaults to LOCALHOST)

        Raises:
            ContainerStateError: If start fails
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            raise ValueError(f"Host not found: {host_name}")

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.info(f"Starting local container: {container_id}")
                client = self.local_manager._ensure_client()
                client.containers.get(container_id).start()
            else:
                logger.info(f"Starting remote container: {container_id}")
                # For remote containers, use the remote manager's client
                self.remote_manager.start_container(host_name=host_name, container_id=container_id)

        except Exception as e:
            logger.error(f"Failed to start container on {host_name}: {e}")
            raise ContainerStateError(f"Failed to start container: {e}")

    def remove_container(
        self, container_id: str, host_name: Optional[str] = None, force: bool = False, volumes: bool = False
    ) -> None:
        """
        Remove a container.

        Args:
            container_id: Container ID
            host_name: Target host (defaults to LOCALHOST)
            force: Force remove
            volumes: Remove volumes

        Raises:
            ContainerStateError: If removal fails
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            raise ValueError(f"Host not found: {host_name}")

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.info(f"Removing local container: {container_id}")
                self.local_manager.remove_container(container_id=container_id, force=force, volumes=volumes)
            else:
                logger.info(f"Removing remote container: {container_id}")
                self.remote_manager.remove_container(host_name=host_name, container_id=container_id)

        except Exception as e:
            logger.error(f"Failed to remove container on {host_name}: {e}")
            raise ContainerStateError(f"Failed to remove container: {e}")

    def list_containers(self, host_name: Optional[str] = None, all: bool = False) -> List[Dict[str, Any]]:
        """
        List containers on specified host.

        Args:
            host_name: Target host (defaults to LOCALHOST)
            all: List all containers (including stopped)

        Returns:
            List of container information dicts
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            logger.warning(f"Host not found: {host_name}")
            return []

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.debug("Listing local containers")
                containers = self.local_manager.list_containers(all=all)
                return [c.to_dict() for c in containers]
            else:
                logger.debug(f"Listing remote containers on {host_name}")
                remote_containers = self.remote_manager.list_containers(host_name=host_name, all=all)
                return remote_containers if remote_containers is not None else []

        except Exception as e:
            logger.error(f"Failed to list containers on {host_name}: {e}")
            return []

    def get_container_info(
        self,
        container_id: str,
        host_name: Optional[str] = None,  # todo
    ) -> Optional[Dict[str, Any]]:
        """
        Get container information.

        Args:
            container_id: Container ID
            host_name: Target host (defaults to LOCALHOST)

        Returns:
            Container information dict or None if failed
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            logger.warning(f"Host not found: {host_name}")
            return None

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.debug(f"Getting info from local container: {container_id}")
                container_info = self.local_manager.get_container_info(container_id)
                return container_info.to_dict() if container_info else None
            else:
                logger.debug(f"Getting info from remote container: {container_id}")
                return self.remote_manager.get_container_info(host_name=host_name, container_id=container_id)

        except Exception as e:
            logger.error(f"Failed to get container info from {host_name}: {e}")
            return None

    def get_container_logs(self, container_id: str, host_name: Optional[str] = None, tail: int = 100) -> Optional[str]:
        """
        Get container logs.

        Args:
            container_id: Container ID
            host_name: Target host (defaults to LOCALHOST)
            tail: Number of log lines

        Returns:
            Log content or None if failed
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            logger.warning(f"Host not found: {host_name}")
            return None

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.debug(f"Getting logs from local container: {container_id}")
                return self.local_manager.get_container_logs(container_id=container_id, tail=tail)
            else:
                logger.debug(f"Getting logs from remote container: {container_id}")
                return self.remote_manager.get_container_logs(host_name=host_name, container_id=container_id, tail=tail)

        except Exception as e:
            logger.error(f"Failed to get logs from {host_name}: {e}")
            return None

    def get_host_info(self, host_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get host information.

        Args:
            host_name: Target host (defaults to LOCALHOST)

        Returns:
            Host information dict or None if failed
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            logger.warning(f"Host not found: {host_name}")
            return None

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.debug("Getting info from local host")
                # Get info from local Docker daemon
                client = self.local_manager._ensure_client()
                info = client.info()
                return {
                    "host_name": LOCALHOST,
                    "docker_version": client.version()["Version"],
                    "os": info.get("OperatingSystem"),
                    "cpu_count": info.get("NCPU"),
                    "memory_bytes": info.get("MemTotal"),
                    "is_local": True,
                }
            else:
                logger.debug(f"Getting info from remote host: {host_name}")
                return self.remote_manager.get_host_info(host_name=host_name)

        except Exception as e:
            logger.error(f"Failed to get host info from {host_name}: {e}")
            return None

    def ping(self, host_name: Optional[str] = None) -> bool:
        """
        Test connection to host.

        Args:
            host_name: Target host (defaults to LOCALHOST)

        Returns:
            True if connection successful, False otherwise
        """
        host_name = host_name or LOCALHOST

        if host_name not in self.hosts:
            logger.warning(f"Host not found: {host_name}")
            return False

        host_config = self.hosts[host_name]

        try:
            if host_config.is_local:
                logger.debug("Pinging local Docker daemon")
                client = self.local_manager._ensure_client()
                client.ping()
                return True
            else:
                logger.debug(f"Pinging remote host: {host_name}")
                # DockerRemoteAPIManager doesn't have ping method, use get_host_info instead
                info = self.remote_manager.get_host_info(host_name=host_name)
                return info is not None

        except Exception as e:
            logger.error(f"Failed to ping {host_name}: {e}")
            return False
