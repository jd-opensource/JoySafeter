"""
Container runtime context management.

Manages Docker container state and execution history.
Supports both local and remote Docker daemon management via Remote API + TLS.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from loguru import logger

from app.dynamic_agent.infra.docker import UnifiedDockerManager

if TYPE_CHECKING:
    from app.dynamic_agent.storage.persistence import PostgreSQLBackend


@dataclass
class RemoteHostInfo:
    """Remote Docker host information."""

    host_name: str  # Unique identifier for the host
    host_ip: str  # Host IP address
    port: int = 2376  # Docker daemon port
    is_local: bool = False  # Whether this is a local Docker daemon


@dataclass
class ContainerContext:
    """Container runtime context."""

    container_id: str
    session_id: str

    # Container information
    image: str
    status: str  # running, stopped, paused

    # Remote host information (for cross-host management)
    remote_host: Optional[RemoteHostInfo] = None

    # File system state
    working_directory: str = "/"
    mounted_volumes: Dict[str, str] = field(default_factory=dict)

    # Environment variables
    environment: Dict[str, str] = field(default_factory=dict)

    # Installed tools
    installed_tools: List[str] = field(default_factory=list)

    # Execution history
    command_history: List[Dict[str, Any]] = field(default_factory=list)

    # Resource usage
    cpu_usage: Optional[float] = None
    memory_usage: Optional[int] = None

    created_at: datetime = field(default_factory=datetime.now)
    last_accessed: datetime = field(default_factory=datetime.now)


class ContainerContextManager:
    """
    Container context manager with Remote API support.

    Supports both local Docker daemon and remote Docker daemon via TLS.
    Enables cross-host container management.
    """

    def __init__(self, docker_manager: UnifiedDockerManager, persistence_backend: "PostgreSQLBackend"):  # noqa: F821
        self.docker_manager = docker_manager
        self.backend = persistence_backend
        self._contexts: Dict[str, ContainerContext] = {}
        logger.info("ContainerContextManager initialized with Remote API support")

    # todo del
    async def create_container_context(
        self, session_id: str, image: str = "kalilinux/kali-rolling", remote_host_name: Optional[str] = None, **kwargs
    ) -> ContainerContext:
        """
        Create container context.

        Args:
            session_id: Session ID
            image: Container image
            remote_host_name: Remote host name for cross-host management
            **kwargs: Additional parameters (cpu_cores, memory_gb, disk_gb, environment, etc.)

        Returns:
            ContainerContext: Created container context
        """
        from app.dynamic_agent.infra.docker import ResourceLimits

        # Create resource limits
        # todo put in config
        ResourceLimits.from_human_readable(
            cpu=str(kwargs.get("cpu_cores", 2)),
            memory=f"{kwargs.get('memory_gb', 4)}G",
            disk=f"{kwargs.get('disk_gb', 20)}G",
        )

        container_info = self.docker_manager.create_container(
            host_name=remote_host_name, image=image, command="sleep infinity", environment=kwargs.get("environment", {})
        )

        # Create remote host info
        remote_host_info = RemoteHostInfo(
            host_name=remote_host_name or "localhost", host_ip="127.0.0.1", port=2376, is_local=remote_host_name is None
        )

        container_id = container_info["container_id"]

        # Create context
        context = ContainerContext(
            container_id=container_id,
            session_id=session_id,
            image=image,
            status="running",
            remote_host=remote_host_info,
            environment=kwargs.get("environment", {}),
        )

        self._contexts[container_id] = context
        await self.backend.save_container(context)

        logger.info(f"Container context created: {container_id} on {remote_host_info.host_name}")
        return context  # type: ignore[return-value]

    async def get_container_context(self, container_id: str) -> Optional[ContainerContext]:
        """Get container context."""
        if container_id in self._contexts:
            return self._contexts[container_id]

        context: Optional[ContainerContext] = await self.backend.load_container(container_id)  # type: ignore[assignment]
        if context:
            self._contexts[container_id] = context

        return context

    async def execute_in_container(
        self, container_id: str, command: str, working_dir: Optional[str] = None, timeout: int = 300
    ) -> Dict[str, Any]:
        """
        Execute command in container.

        Supports both local and remote containers.

        Args:
            container_id: Container ID
            command: Command to execute
            working_dir: Working directory (optional)
            timeout: Command execution timeout in seconds

        Returns:
            Execution record with exit_code, stdout, stderr
        """
        context = await self.get_container_context(container_id)
        if not context:
            raise ValueError(f"Container context {container_id} not found")

        # Execute command based on host type
        if context.remote_host and not context.remote_host.is_local:
            logger.info(f"Executing command on remote host: {context.remote_host.host_name}")
            result = self.docker_manager.remote_manager.execute_command(
                host_name=context.remote_host.host_name, container_id=container_id, command=command, timeout=timeout
            )

            if not result:
                raise RuntimeError(f"Failed to execute command on remote container {container_id}")

            exit_code, stdout, stderr = result
        else:
            logger.info(f"Executing command on local container: {container_id}")
            exit_code, stdout, stderr = self.docker_manager.execute_command(container_id, command)

        # Record execution
        execution_record = {
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "timestamp": datetime.now().isoformat(),
            "working_dir": working_dir or context.working_directory,
            "host": context.remote_host.host_name if context.remote_host else "local",
        }

        context.command_history.append(execution_record)
        context.last_accessed = datetime.now()
        await self.backend.save_container(context)

        logger.debug(f"Command executed: {command} (exit_code={exit_code})")
        return execution_record

    async def update_working_directory(self, container_id: str, directory: str):
        """Update working directory."""
        context = await self.get_container_context(container_id)
        if context:
            context.working_directory = directory
            context.last_accessed = datetime.now()
            await self.backend.save_container(context)

    async def add_installed_tool(self, container_id: str, tool_name: str):
        """Record installed tool."""
        context = await self.get_container_context(container_id)
        if context and tool_name not in context.installed_tools:
            context.installed_tools.append(tool_name)
            context.last_accessed = datetime.now()
            await self.backend.save_container(context)

    async def get_command_history(self, container_id: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get command execution history."""
        context = await self.get_container_context(container_id)
        if not context:
            return []

        history = context.command_history
        if limit:
            history = history[-limit:]

        return history

    async def update_resource_usage(
        self, container_id: str, cpu_usage: Optional[float] = None, memory_usage: Optional[int] = None
    ):
        """Update resource usage statistics."""
        context = await self.get_container_context(container_id)
        if context:
            if cpu_usage is not None:
                context.cpu_usage = cpu_usage
            if memory_usage is not None:
                context.memory_usage = memory_usage
            context.last_accessed = datetime.now()
            await self.backend.save_container(context)

    async def stop_container(self, container_id: str):
        """
        Stop container.

        Supports both local and remote containers.
        """
        context = await self.get_container_context(container_id)
        if context:
            if context.remote_host and not context.remote_host.is_local:
                logger.info(f"Stopping remote container: {container_id} on {context.remote_host.host_name}")
                self.docker_manager.remote_manager.stop_container(
                    host_name=context.remote_host.host_name, container_id=container_id
                )
            else:
                logger.info(f"Stopping local container: {container_id}")
                self.docker_manager.stop_container(container_id)

            context.status = "stopped"
            await self.backend.save_container(context)

    async def remove_container(self, container_id: str):
        """
        Remove container.

        Supports both local and remote containers.
        """
        context = await self.get_container_context(container_id)
        if context:
            if context.remote_host and not context.remote_host.is_local:
                logger.info(f"Removing remote container: {container_id} on {context.remote_host.host_name}")
                self.docker_manager.remote_manager.remove_container(
                    host_name=context.remote_host.host_name, container_id=container_id
                )
            else:
                logger.info(f"Removing local container: {container_id}")
                self.docker_manager.remove_container(container_id)

            if container_id in self._contexts:
                del self._contexts[container_id]

    async def get_container_logs(self, container_id: str, tail: int = 100) -> Optional[str]:
        """
        Get container logs.

        Supports both local and remote containers.

        Args:
            container_id: Container ID
            tail: Number of log lines

        Returns:
            Log content or None if failed
        """
        context = await self.get_container_context(container_id)
        if not context:
            return None

        if context.remote_host and not context.remote_host.is_local:
            logger.info(f"Getting logs from remote container: {container_id}")
            logs = self.docker_manager.remote_manager.get_container_logs(
                host_name=context.remote_host.host_name, container_id=container_id, tail=tail
            )
        else:
            logger.info(f"Getting logs from local container: {container_id}")
            logs = self.docker_manager.get_container_logs(container_id, tail=tail)

        return str(logs) if logs is not None else None

    async def get_host_info(self, container_id: str) -> Optional[Dict[str, Any]]:
        """
        Get host information for a container.

        Args:
            container_id: Container ID

        Returns:
            Host information dict or None if failed
        """
        context = await self.get_container_context(container_id)
        if not context or not context.remote_host:
            return None

        if context.remote_host.is_local:
            return {"host_name": "localhost", "host_ip": "127.0.0.1", "is_local": True}

        logger.info(f"Getting host info for remote container: {container_id}")
        host_info = self.docker_manager.remote_manager.get_host_info(host_name=context.remote_host.host_name)

        return host_info
