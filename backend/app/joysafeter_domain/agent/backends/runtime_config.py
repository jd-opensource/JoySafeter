"""Runtime configuration for Docker sandbox environments.

This module provides RuntimeConfig dataclass and pre-defined runtime configurations
for commonly used development environments (Python data science, web, ML, Node.js, etc.).

Features:
- RuntimeConfig dataclass for defining custom runtime environments
- BUILTIN_RUNTIMES dictionary with pre-configured environments
- Helper functions for runtime management
- Compatibility with pydantic-ai-backend's RuntimeConfig
"""

from dataclasses import dataclass, field

from loguru import logger
from pydantic_ai_backends import RuntimeConfig as PydanticRuntimeConfig


@dataclass
class RuntimeConfig:
    """Pre-configured runtime environment configuration.

    Defines Docker sandbox runtime environment including base image,
    pre-installed packages, setup commands, and environment variables.
    Compatible with pydantic-ai-backend's RuntimeConfig API.

    Attributes:
        name: Runtime name identifier
        base_image: Docker base image (default: python:3.12-slim)
        packages: List of Python packages to pre-install
        setup_commands: Commands to execute after container starts
        env_vars: Environment variables dictionary

    Example:
        ```python
        # Create a custom machine learning runtime
        ml_runtime = RuntimeConfig(
            name="ml-env",
            base_image="python:3.12-slim",
            packages=["torch", "transformers", "numpy"],
            setup_commands=["pip install --upgrade pip"],
            env_vars={"CUDA_VISIBLE_DEVICES": "0"},
        )
        ```
    """

    name: str
    base_image: str = "python:3.12-slim"
    packages: list[str] = field(default_factory=list)
    setup_commands: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)

    def to_pydantic_runtime(self) -> "PydanticRuntimeConfig | RuntimeConfig":
        """Convert to pydantic-ai-backend's RuntimeConfig (if available).

        Returns:
            pydantic-ai-backend RuntimeConfig instance, or self if library not available
        """
        return PydanticRuntimeConfig(
            name=self.name,
            base_image=self.base_image,
            packages=self.packages,
        )
        return self


# Pre-defined runtime configurations
BUILTIN_RUNTIMES: dict[str, RuntimeConfig] = {
    "python-minimal": RuntimeConfig(
        name="python-minimal",
        base_image="python:3.12-slim",
        packages=[],
    ),
    "python-datascience": RuntimeConfig(
        name="python-datascience",
        base_image="python:3.12-slim",
        packages=["pandas", "numpy", "matplotlib", "scikit-learn", "scipy"],
    ),
    "python-web": RuntimeConfig(
        name="python-web",
        base_image="python:3.12-slim",
        packages=["fastapi", "uvicorn", "sqlalchemy", "httpx", "aiohttp"],
    ),
    "python-ml": RuntimeConfig(
        name="python-ml",
        base_image="python:3.12-slim",
        packages=["torch", "transformers", "numpy", "pandas"],
    ),
    "node-minimal": RuntimeConfig(
        name="node-minimal",
        base_image="node:20-slim",
        packages=[],
    ),
    "node-react": RuntimeConfig(
        name="node-react",
        base_image="node:20-slim",
        packages=["typescript", "vite", "react", "react-dom"],
    ),
}


def get_builtin_runtime(name: str) -> RuntimeConfig | None:
    """Get a pre-defined runtime configuration.

    Args:
        name: Runtime name

    Returns:
        RuntimeConfig instance, or None if not found
    """
    return BUILTIN_RUNTIMES.get(name)


def list_builtin_runtimes() -> list[str]:
    """List all available pre-defined runtime names.

    Returns:
        List of pre-defined runtime names
    """
    return list(BUILTIN_RUNTIMES.keys())


def resolve_runtime(
    default_image: str,
    runtime: "RuntimeConfig | str | None",
) -> tuple[str, RuntimeConfig | None]:
    """Resolve runtime configuration to effective image and config.

    Args:
        default_image: Default Docker image (used when runtime is None)
        runtime: Runtime configuration, can be:
                 - None: Use default_image
                 - str: Pre-defined runtime name or image name
                 - RuntimeConfig: Custom runtime configuration

    Returns:
        Tuple of (effective_image, runtime_config)
        - effective_image: Docker image to use
        - runtime_config: RuntimeConfig instance or None

    Example:
        >>> image, config = resolve_runtime("python:3.12-slim", "python-datascience")
        >>> print(image)  # "python:3.12-slim"
        >>> print(config.packages)  # ["pandas", "numpy", ...]
    """
    if runtime is None:
        logger.debug(f"No runtime specified, using default image: {default_image}")
        return default_image, None

    if isinstance(runtime, str):
        # First check if it's a pre-defined runtime
        if runtime in BUILTIN_RUNTIMES:
            config = BUILTIN_RUNTIMES[runtime]
            logger.info(f"Using builtin runtime '{runtime}': image={config.base_image}")
            return config.base_image, config

        # Check if it looks like an image name (contains ':' or '/')
        if ":" in runtime or "/" in runtime:
            logger.info(f"Using runtime string as image name: {runtime}")
            return runtime, None

        # Neither pre-defined runtime nor looks like image name
        available_runtimes = list(BUILTIN_RUNTIMES.keys())
        logger.warning(
            f"Runtime '{runtime}' not found in builtin runtimes: {available_runtimes}. Treating as image name."
        )
        return runtime, None

    # RuntimeConfig instance
    if isinstance(runtime, RuntimeConfig):
        logger.info(f"Using custom RuntimeConfig '{runtime.name}': image={runtime.base_image}")
        return runtime.base_image, runtime

    # Try to handle pydantic-ai-backend's RuntimeConfig
    if hasattr(runtime, "base_image") and hasattr(runtime, "name"):
        logger.info(f"Using pydantic RuntimeConfig '{runtime.name}': image={runtime.base_image}")
        # Convert to local RuntimeConfig
        local_config = RuntimeConfig(
            name=runtime.name,
            base_image=runtime.base_image,
            packages=getattr(runtime, "packages", []),
        )
        return runtime.base_image, local_config

    # Unknown type, use default image
    logger.warning(f"Unknown runtime type: {type(runtime)}, using default image: {default_image}")
    return default_image, None


__all__ = [
    "RuntimeConfig",
    "BUILTIN_RUNTIMES",
    "get_builtin_runtime",
    "list_builtin_runtimes",
    "resolve_runtime",
]
