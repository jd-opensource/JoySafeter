from typing import Optional

from loguru import logger

from app.dynamic_agent.infra.docker import UnifiedDockerManager
from app.dynamic_agent.infra.tool_registry import ToolRegistry

tool_registry: ToolRegistry = ToolRegistry()

# Initialize Docker manager with error handling
# If Docker is not available (e.g., in container without socket mount),
# the manager will be None and Docker-dependent features will be disabled
try:
    docker_manager: Optional[UnifiedDockerManager] = UnifiedDockerManager()
    logger.info("Docker manager initialized successfully")
except Exception as e:
    logger.warning(f"Failed to initialize Docker manager: {e}")
    logger.warning(
        "Docker-dependent features will be disabled. "
        "To enable Docker, mount the socket: -v /var/run/docker.sock:/var/run/docker.sock"
    )
    docker_manager = None
