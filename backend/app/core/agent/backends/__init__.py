from app.core.agent.backends.filesystem_sandbox import FilesystemSandboxBackend
from app.core.agent.backends.state_sandbox import StateSandboxBackend

try:
    from app.core.agent.backends.pydantic_adapter import (
        PYDANTIC_BACKEND_AVAILABLE,
        PydanticSandboxAdapter,
    )
except ImportError:
    PydanticSandboxAdapter = None  # type: ignore
    PYDANTIC_BACKEND_AVAILABLE = False

try:
    from app.core.agent.backends.docker_sandbox import (
        DockerSandboxBackend,
    )

    DOCKER_SANDBOX_BACKEND_AVAILABLE = True
except ImportError:
    DockerSandboxBackend = None  # type: ignore
    DOCKER_SANDBOX_BACKEND_AVAILABLE = False

__all__ = [
    "StateSandboxBackend",
    "FilesystemSandboxBackend",
    "PydanticSandboxAdapter",
    "PYDANTIC_BACKEND_AVAILABLE",
    "DockerSandboxBackend",
    "DOCKER_SANDBOX_BACKEND_AVAILABLE",
]
