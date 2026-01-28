"""
Docker Remote API with TLS support for multi-host container management

Enables secure communication with Docker daemons on remote hosts using TLS certificates.
Supports both local and remote Docker daemon connections.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import docker
from docker.errors import ImageNotFound
from loguru import logger

from app.dynamic_agent.core.constants import DOCKER_RUN_CAPS, DOCKER_RUN_GROUP, DOCKER_RUN_USER


@dataclass
class TLSConfig:
    """TLS configuration for Docker Remote API"""

    client_cert: str  # Path to client certificate
    client_key: str  # Path to client key
    ca_cert: str  # Path to CA certificate
    verify: bool = True  # Verify server certificate

    def validate(self) -> bool:
        """Validate TLS certificate files exist"""
        for path in [self.client_cert, self.client_key, self.ca_cert]:
            if not Path(path).exists():
                logger.error(f"TLS file not found: {path}")
                return False
        return True

    def to_docker_tls(self) -> docker.tls.TLSConfig:
        """Convert to docker.tls.TLSConfig"""
        return docker.tls.TLSConfig(
            client_cert=(self.client_cert, self.client_key), ca_cert=self.ca_cert, verify=self.verify
        )


@dataclass
class RemoteDockerHost:
    """Remote Docker host configuration"""

    host: str  # Host IP or hostname (e.g., 192.168.1.10)
    port: int = 2376  # Docker daemon port (default 2376 for TLS)
    tls_config: Optional[TLSConfig] = None
    name: Optional[str] = None  # Friendly name for the host

    @property
    def base_url(self) -> str:
        """Get Docker daemon URL"""
        return f"tcp://{self.host}:{self.port}"

    def __str__(self) -> str:
        return self.name or f"{self.host}:{self.port}"


class DockerRemoteAPIManager:
    """
    Docker Remote API manager with TLS support

    Enables management of Docker containers on remote hosts using secure TLS connections.

    Example:
        >>> # Configure remote host with TLS
        >>> tls = TLSConfig(
        ...     client_cert='/path/to/cert.pem',
        ...     client_key='/path/to/key.pem',
        ...     ca_cert='/path/to/ca.pem'
        ... )
        >>> remote_host = RemoteDockerHost(
        ...     host='192.168.1.10',
        ...     port=2376,
        ...     tls_config=tls,
        ...     name='remote-server-1'
        ... )
        >>> manager = DockerRemoteAPIManager()
        >>> manager.add_host(remote_host)
        >>> container = manager.create_container(
        ...     host_name='remote-server-1',
        ...     image='ubuntu:20.04',
        ...     command='sleep 3600'
        ... )
    """

    def __init__(self):
        """Initialize Docker Remote API manager"""
        self.hosts: Dict[str, RemoteDockerHost] = {}
        self.clients: Dict[str, docker.DockerClient] = {}
        logger.info("Docker Remote API manager initialized")

    def add_host(self, host: RemoteDockerHost) -> bool:
        """
        Add a remote Docker host

        Args:
            host: Remote Docker host configuration

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Validate TLS config if provided
            if host.tls_config and not host.tls_config.validate():
                logger.error(f"Invalid TLS configuration for {host}")
                return False

            # Create Docker client
            if host.tls_config:
                tls = host.tls_config.to_docker_tls()
                client = docker.DockerClient(base_url=host.base_url, tls=tls, timeout=30)
            else:
                client = docker.DockerClient(base_url=host.base_url, timeout=30)

            # Test connection
            client.ping()

            # Store host and client
            host_name = host.name or host.host
            self.hosts[host_name] = host
            self.clients[host_name] = client

            logger.info(f"Successfully connected to Docker host: {host}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to Docker host {host}: {e}")
            return False

    def remove_host(self, host_name: str) -> bool:
        """
        Remove a remote Docker host

        Args:
            host_name: Host name or identifier

        Returns:
            True if successful, False otherwise
        """
        try:
            if host_name in self.hosts:
                del self.hosts[host_name]
            if host_name in self.clients:
                del self.clients[host_name]
            logger.info(f"Removed Docker host: {host_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove host {host_name}: {e}")
            return False

    def list_hosts(self) -> List[RemoteDockerHost]:
        """Get list of configured hosts"""
        return list(self.hosts.values())

    def get_client(self, host_name: str) -> Optional[docker.DockerClient]:
        """Get Docker client for a specific host"""
        return self.clients.get(host_name)

    def create_container(
        self,
        host_name: str,
        image: str,
        command: Optional[str] = None,
        name: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        ports: Optional[Dict[str, int]] = None,
        volumes: Optional[Dict[str, Dict[str, str]]] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """
        Create container on remote host

        Args:
            host_name: Target host name
            image: Container image
            command: Container command
            name: Container name
            environment: Environment variables
            ports: Port mappings
            volumes: Volume mounts
            **kwargs: Additional Docker parameters

        Returns:
            Container info dict or None if failed
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return None

            # Pull image if not exists
            try:
                client.images.get(image)
            except ImageNotFound:
                logger.info(f"Pulling image {image} on {host_name}...")
                client.images.pull(image)

            # Build container parameters
            container_kwargs: Dict[str, Any] = {
                "image": image,
                "command": command,
                "detach": True,
            }

            if name:
                container_kwargs["name"] = name
            if environment:
                container_kwargs["environment"] = environment
            if ports:
                # Convert ports format if needed
                container_kwargs["ports"] = ports
            if volumes:
                container_kwargs["volumes"] = volumes

            #  user=f"{uid}:{gid}"
            container_kwargs["user"] = f"{os.environ[DOCKER_RUN_USER]}:{os.environ[DOCKER_RUN_GROUP]}"
            container_kwargs["cap_add"] = DOCKER_RUN_CAPS

            container_kwargs.update(kwargs)

            # Create container
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

            logger.info(f"Container created on {host_name}: {container.short_id}")

            return {
                "host": host_name,
                "container_id": container.id,
                "container_short_id": container.short_id,
                "name": container.name,
                "image": image,
                "status": container.status,
            }

        except Exception as e:
            logger.error(f"Failed to create container on {host_name}: {e}")
            raise e

    def execute_command(
        self,
        host_name: str,
        container_id: str,
        command: str,
        timeout: Optional[int] = None,
    ) -> Optional[Tuple[int, str, str]]:
        """
        Execute command in container on remote host

        Args:
            host_name: Target host name
            container_id: Container ID or name
            command: Command to execute
            timeout: Execution timeout

        Returns:
            Tuple of (exit_code, stdout, stderr) or None if failed
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return None

            container = client.containers.get(container_id)
            result = container.exec_run(cmd=command, stdout=True, stderr=True, timeout=timeout)

            exit_code = result.exit_code
            stdout = result.output.decode("utf-8", errors="ignore") if result.output else ""
            stderr = ""

            logger.debug(f"Command executed on {host_name}: {command} (exit_code={exit_code})")
            return exit_code, stdout, stderr

        except Exception as e:
            logger.error(f"Failed to execute command on {host_name}: {e}")
            return None

    def stop_container(
        self,
        host_name: str,
        container_id: str,
        timeout: int = 10,
        force: bool = False,
    ) -> bool:
        """
        Stop container on remote host

        Args:
            host_name: Target host name
            container_id: Container ID or name
            timeout: Stop timeout
            force: Force stop (SIGKILL)

        Returns:
            True if successful, False otherwise
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return False

            container = client.containers.get(container_id)

            if force:
                container.kill()
            else:
                container.stop(timeout=timeout)

            logger.info(f"Container stopped on {host_name}: {container_id[:12]}")
            return True

        except Exception as e:
            logger.error(f"Failed to stop container on {host_name}: {e}")
            return False

    def start_container(
        self,
        host_name: str,
        container_id: str,
    ) -> bool:
        """
        Start a stopped container on remote host

        Args:
            host_name: Target host name
            container_id: Container ID or name

        Returns:
            True if successful, False otherwise
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return False

            container = client.containers.get(container_id)
            container.start()

            logger.info(f"Container started on {host_name}: {container_id[:12]}")
            return True

        except Exception as e:
            logger.error(f"Failed to start container on {host_name}: {e}")
            return False

    def remove_container(
        self,
        host_name: str,
        container_id: str,
        force: bool = False,
        volumes: bool = False,
    ) -> bool:
        """
        Remove container on remote host

        Args:
            host_name: Target host name
            container_id: Container ID or name
            force: Force remove
            volumes: Remove volumes

        Returns:
            True if successful, False otherwise
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return False

            container = client.containers.get(container_id)
            container.remove(force=force, v=volumes)

            logger.info(f"Container removed on {host_name}: {container_id[:12]}")
            return True

        except Exception as e:
            logger.error(f"Failed to remove container on {host_name}: {e}")
            return False

    def list_containers(
        self,
        host_name: str,
        all: bool = False,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        List containers on remote host

        Args:
            host_name: Target host name
            all: List all containers (including stopped)

        Returns:
            List of container info dicts or None if failed
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return None

            containers = client.containers.list(all=all)

            return [
                {
                    "id": c.id,
                    "short_id": c.short_id,
                    "name": c.name,
                    "image": c.image.tags[0] if c.image.tags else "unknown",
                    "status": c.status,
                    "created": c.attrs.get("Created"),
                }
                for c in containers
            ]

        except Exception as e:
            logger.error(f"Failed to list containers on {host_name}: {e}")
            return None

    def get_container_info(
        self,
        host_name: str,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Get container information from remote host

        Args:
            host_name: Target host name
            container_id: Container ID or name

        Returns:
            Container info dict or None if failed
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return None

            container = client.containers.get(container_id)

            return {
                "id": container.id,
                "short_id": container.short_id,
                "name": container.name,
                "image": container.image.tags[0] if container.image.tags else "unknown",
                "status": container.status,
                "created": container.attrs.get("Created"),
                "state": container.attrs.get("State", {}),
                "config": container.attrs.get("Config", {}),
            }

        except Exception as e:
            logger.error(f"Failed to get container info from {host_name}: {e}")
            return None

    def get_container_logs(
        self,
        host_name: str,
        container_id: str,
        tail: int = 100,
    ) -> Optional[str]:
        """
        Get container logs from remote host

        Args:
            host_name: Target host name
            container_id: Container ID or name
            tail: Number of log lines

        Returns:
            Log content or None if failed
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return None

            container = client.containers.get(container_id)
            logs = container.logs(tail=tail)

            decoded = logs.decode("utf-8", errors="ignore")
            return str(decoded) if decoded is not None else None

        except Exception as e:
            logger.error(f"Failed to get logs from {host_name}: {e}")
            return None

    def get_host_info(self, host_name: str) -> Optional[Dict[str, Any]]:
        """
        Get Docker host information

        Args:
            host_name: Target host name

        Returns:
            Host info dict or None if failed
        """
        try:
            client = self.get_client(host_name)
            if not client:
                logger.error(f"Host not found: {host_name}")
                return None

            info = client.info()

            return {
                "host": host_name,
                "docker_version": client.version()["Version"],
                "os": info.get("OperatingSystem"),
                "kernel_version": info.get("KernelVersion"),
                "cpu_count": info.get("NCPU"),
                "memory_bytes": info.get("MemTotal"),
                "containers_total": info.get("Containers"),
                "containers_running": info.get("ContainersRunning"),
                "containers_paused": info.get("ContainersPaused"),
                "containers_stopped": info.get("ContainersStopped"),
            }

        except Exception as e:
            logger.error(f"Failed to get host info from {host_name}: {e}")
            return None

    def cleanup(self):
        """Cleanup all connections"""
        self.hosts.clear()
        self.clients.clear()
        logger.info("Docker Remote API manager cleaned up")
