"""
Docker container management system

Provides complete Docker container management functionality:
- Dynamic container creation and destruction
- Container command execution
- Resource limits (CPU, memory, disk, process count)
- Resource monitoring and metrics collection
- Container lifecycle management

Example:
    >>> from app.dynamic_agent.infra.docker import DockerManager, ResourceLimits
    >>>
    >>> # Create manager
    >>> manager = DockerManager()
    >>>
    >>> # Define resource limits
    >>> limits = ResourceLimits.from_human_readable(
    ...     cpu='1',
    ...     memory='512M',
    ...     disk='10G'
    ... )
    >>>
    >>> # Create container
    >>> container = manager.create_container(
    ...     image='ubuntu:20.04',
    ...     command='sleep 3600',
    ...     name='test-container',
    ...     resource_limits=limits
    ... )
    >>>
    >>> # Execute command
    >>> exit_code, stdout, stderr = manager.execute_command(
    ...     container.id,
    ...     'ls -la /tmp'
    ... )
    >>>
    >>> # Monitor resources
    >>> metrics = manager.monitor_resources(
    ...     container.id,
    ...     duration=30,
    ...     interval=1
    ... )
    >>> print(f"Average CPU: {metrics.get_avg_cpu()}%")
    >>> print(f"Max memory: {metrics.get_max_memory()} bytes")
    >>>
    >>> # Stop and remove container
    >>> manager.stop_container(container.id)
    >>> manager.remove_container(container.id)
"""

from .colima_helper import ColimaHelper
from .colima_init import ColimaDockerSetup
from .docker_manager import ContainerInfo, DockerManager
from .docker_remote_api import DockerRemoteAPIManager, RemoteDockerHost, TLSConfig
from .docker_tls_setup import DockerTLSSetup
from .docker_unified_manager import HostConfig, UnifiedDockerManager
from .exceptions import (
    ContainerCreationError,
    ContainerExecutionError,
    ContainerNotFoundError,
    ContainerStateError,
    DockerConnectionError,
    DockerException,
    ResourceLimitError,
    ResourceMonitorError,
)
from .resource_limiter import ResourceLimits
from .resource_monitor import ResourceMetrics, ResourceMonitor, ResourceSnapshot

__all__ = [
    # Core managers
    "DockerManager",
    "ContainerInfo",
    "UnifiedDockerManager",
    "HostConfig",
    # Resource management
    "ResourceLimits",
    "ResourceMonitor",
    "ResourceMetrics",
    "ResourceSnapshot",
    # Remote API with TLS
    "DockerRemoteAPIManager",
    "RemoteDockerHost",
    "TLSConfig",
    "DockerTLSSetup",
    # Colima support
    "ColimaHelper",
    "ColimaDockerSetup",
    # Exceptions
    "DockerException",
    "DockerConnectionError",
    "ContainerCreationError",
    "ContainerExecutionError",
    "ResourceLimitError",
    "ResourceMonitorError",
    "ContainerNotFoundError",
    "ContainerStateError",
]
