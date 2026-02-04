"""Sandbox lifecycle management with context managers."""

import os
import shlex
import string
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ContextManager

from deepagents.backends.protocol import SandboxBackendProtocol
from loguru import logger

if TYPE_CHECKING:
    from app.core.agent.backends.pydantic_adapter import RuntimeConfig


def _run_sandbox_setup(backend: SandboxBackendProtocol, setup_script_path: str) -> None:
    """Run users setup script in sandbox with env var expansion.

    Args:
        backend: Sandbox backend instance
        setup_script_path: Path to setup script file
    """
    script_path = Path(setup_script_path)
    if not script_path.exists():
        msg = f"Setup script not found: {setup_script_path}"
        raise FileNotFoundError(msg)

    logger.info(f"[dim]Running setup script: {setup_script_path}...[/dim]")

    # Read script content
    script_content = script_path.read_text()

    # Expand ${VAR} syntax using local environment
    template = string.Template(script_content)
    expanded_script = template.safe_substitute(os.environ)

    # Execute in sandbox with 5-minute timeout
    result = backend.execute(f"bash -c {shlex.quote(expanded_script)}")

    if result.exit_code != 0:
        logger.info(f"[red]❌ Setup script failed (exit {result.exit_code}):[/red]")
        logger.info(f"[dim]{result.output}[/dim]")
        msg = "Setup failed - aborting"
        raise RuntimeError(msg)

    logger.info("[green]✓ Setup complete[/green]")


@contextmanager
def create_modal_sandbox(
    *, sandbox_id: str | None = None, setup_script_path: str | None = None
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to Modal sandbox.

    Args:
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        (ModalBackend, sandbox_id)

    Raises:
        ImportError: Modal SDK not installed
        Exception: Sandbox creation/connection failed
        FileNotFoundError: Setup script not found
        RuntimeError: Setup script failed
    """
    import modal

    from app.core.tools.sandbox.modal import ModalBackend

    logger.info("[yellow]Starting Modal sandbox...[/yellow]")

    # Create ephemeral app (auto-cleans up on exit)
    app = modal.App("deepagents-sandbox")

    with app.run():
        if sandbox_id:
            sandbox = modal.Sandbox.from_id(sandbox_id=sandbox_id)  # type: ignore[call-arg]
            should_cleanup = False
        else:
            sandbox = modal.Sandbox.create(app=app, workdir="/workspace")
            should_cleanup = True

            # Poll until running (Modal requires this)
            for _ in range(90):  # 180s timeout (90 * 2s)
                if sandbox.poll() is not None:  # Sandbox terminated unexpectedly
                    msg = "Modal sandbox terminated unexpectedly during startup"
                    raise RuntimeError(msg)
                # Check if sandbox is ready by attempting a simple command
                try:
                    process = sandbox.exec("echo", "ready", timeout=5)
                    process.wait()
                    if process.returncode == 0:
                        break
                except Exception:
                    pass
                time.sleep(2)
            else:
                # Timeout - cleanup and fail
                sandbox.terminate()
                msg = "Modal sandbox failed to start within 180 seconds"
                raise RuntimeError(msg)

        backend = ModalBackend(sandbox)
        logger.info(f"[green]✓ Modal sandbox ready: {backend.id}[/green]")

        # Run setup script if provided
        if setup_script_path:
            _run_sandbox_setup(backend, setup_script_path)
        try:
            yield backend
        finally:
            if should_cleanup:
                try:
                    logger.info(f"[dim]Terminating Modal sandbox {sandbox_id}...[/dim]")
                    sandbox.terminate()
                    logger.info(f"[dim]✓ Modal sandbox {sandbox_id} terminated[/dim]")
                except Exception as e:
                    logger.info(f"[yellow]⚠ Cleanup failed: {e}[/yellow]")


@contextmanager
def create_runloop_sandbox(
    *, sandbox_id: str | None = None, setup_script_path: str | None = None
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to Runloop devbox.

    Args:
        sandbox_id: Optional existing devbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        (RunloopBackend, devbox_id)

    Raises:
        ImportError: Runloop SDK not installed
        ValueError: RUNLOOP_API_KEY not set
        RuntimeError: Devbox failed to start within timeout
        FileNotFoundError: Setup script not found
        RuntimeError: Setup script failed
    """
    from runloop_api_client import Runloop

    from app.core.tools.sandbox.runloop import RunloopBackend

    bearer_token = os.environ.get("RUNLOOP_API_KEY")
    if not bearer_token:
        msg = "RUNLOOP_API_KEY environment variable not set"
        raise ValueError(msg)

    client = Runloop(bearer_token=bearer_token)

    logger.info("[yellow]Starting Runloop devbox...[/yellow]")

    if sandbox_id:
        devbox = client.devboxes.retrieve(id=sandbox_id)
        should_cleanup = False
    else:
        devbox = client.devboxes.create()
        sandbox_id = devbox.id
        should_cleanup = True

        # Poll until running (Runloop requires this)
        for _ in range(90):  # 180s timeout (90 * 2s)
            status = client.devboxes.retrieve(id=devbox.id)
            if status.status == "running":
                break
            time.sleep(2)
        else:
            # Timeout - cleanup and fail
            client.devboxes.shutdown(id=devbox.id)
            msg = "Devbox failed to start within 180 seconds"
            raise RuntimeError(msg)

    logger.info(f"[green]✓ Runloop devbox ready: {sandbox_id}[/green]")

    backend = RunloopBackend(devbox_id=devbox.id, client=client)

    # Run setup script if provided
    if setup_script_path:
        _run_sandbox_setup(backend, setup_script_path)
    try:
        yield backend
    finally:
        if should_cleanup:
            try:
                logger.info(f"[dim]Shutting down Runloop devbox {sandbox_id}...[/dim]")
                client.devboxes.shutdown(id=devbox.id)
                logger.info(f"[dim]✓ Runloop devbox {sandbox_id} terminated[/dim]")
            except Exception as e:
                logger.info(f"[yellow]⚠ Cleanup failed: {e}[/yellow]")


@contextmanager
def create_docker_sandbox(
    *,
    runtime: "RuntimeConfig | str | None" = None,
    image: str = "python:3.12-slim",
    session_id: str | None = None,
    idle_timeout: int = 3600,
    volumes: dict[str, str] | None = None,
    working_dir: str = "/workspace",
    setup_script_path: str | None = None,
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create a Docker sandbox using pydantic-ai-backend.

    This factory function creates an isolated Docker sandbox environment
    for safe code execution. Supports pre-configured runtimes, session
    management, and volume mounting.

    Args:
        runtime: Pre-configured runtime environment. Can be:
                 - str: Name of builtin runtime ("python-datascience", "python-web", etc.)
                 - RuntimeConfig: Custom runtime configuration
                 - None: Use image parameter directly
        image: Docker image to use (default: python:3.12-slim).
               Ignored if runtime is specified.
        session_id: Session identifier for multi-user scenarios.
        idle_timeout: Time in seconds before idle container is cleaned up (default: 3600)
        volumes: Docker volume mappings {host_path: container_path}
        working_dir: Working directory in container
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        PydanticSandboxAdapter instance

    Raises:
        ImportError: pydantic-ai-backend[docker] not installed
        RuntimeError: Sandbox creation or startup failed
        FileNotFoundError: Setup script not found
        RuntimeError: Setup script failed

    Example:
        ```python
        from app.core.tools.sandbox.sandbox_factory import create_docker_sandbox

        # Using pre-configured runtime
        with create_docker_sandbox(runtime="python-datascience") as sandbox:
            result = sandbox.execute("python -c 'import pandas; print(pandas.__version__)'")

        # Using custom configuration
        with create_docker_sandbox(
            image="python:3.11",
            volumes={"/data": "/workspace/data"},
        ) as sandbox:
            result = sandbox.execute("ls -la /workspace/data")

        # With session management
        with create_docker_sandbox(
            runtime="python-web",
            session_id="user-123",
            idle_timeout=1800,
        ) as sandbox:
            # Use sandbox...
            pass
        ```
    """
    # Import here to avoid circular imports and allow graceful failure
    try:
        from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter
    except ImportError as e:
        msg = "pydantic-ai-backend[docker] is required. Install with: pip install pydantic-ai-backend[docker]"
        raise ImportError(msg) from e

    # Resolve runtime if it's a string
    resolved_runtime = None
    if runtime is not None:
        if isinstance(runtime, str):
            from app.core.agent.backends.pydantic_adapter import BUILTIN_RUNTIMES

            if runtime in BUILTIN_RUNTIMES:
                resolved_runtime = BUILTIN_RUNTIMES[runtime]
            else:
                # Treat as image name, not a runtime
                image = runtime
                resolved_runtime = None
        else:
            resolved_runtime = runtime

    runtime_info = f"runtime={resolved_runtime.name if resolved_runtime else None}, "
    logger.info(f"[yellow]Starting Docker sandbox: {runtime_info}image={image}, session_id={session_id}[/yellow]")

    try:
        backend = PydanticSandboxAdapter(
            image=image,
            working_dir=working_dir,
            runtime=resolved_runtime,
            session_id=session_id,
            idle_timeout=idle_timeout,
            volumes=volumes,
        )
        logger.info(f"[green]✓ Docker sandbox ready: {backend.id}[/green]")

        # Run setup script if provided
        if setup_script_path:
            _run_sandbox_setup(backend, setup_script_path)

        try:
            yield backend
        finally:
            try:
                logger.info(f"[dim]Stopping Docker sandbox {backend.id}...[/dim]")
                backend.cleanup()
                logger.info(f"[dim]✓ Docker sandbox {backend.id} terminated[/dim]")
            except Exception as e:
                logger.warning(f"[yellow]⚠ Docker sandbox cleanup failed: {e}[/yellow]")

    except Exception as e:
        logger.error(f"[red]Failed to create Docker sandbox: {e}[/red]")
        raise


_PROVIDER_TO_WORKING_DIR = {
    "modal": "/workspace",
    "runloop": "/home/user",
    "docker": "/workspace",
}


# Mapping of sandbox types to their context manager factories
_SANDBOX_PROVIDERS: dict[str, Callable[..., ContextManager[SandboxBackendProtocol]]] = {
    "modal": create_modal_sandbox,
    "runloop": create_runloop_sandbox,
    "docker": create_docker_sandbox,
}


@contextmanager
def create_sandbox(
    provider: str,
    *,
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
) -> Generator[SandboxBackendProtocol, None, None]:
    """Create or connect to a sandbox of the specified provider.

    This is the unified interface for sandbox creation that delegates to
    the appropriate provider-specific context manager.

    Args:
        provider: Sandbox provider ("modal", "runloop", "docker")
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run after sandbox starts

    Yields:
        SandboxBackend instance
    """
    if provider not in _SANDBOX_PROVIDERS:
        msg = f"Unknown sandbox provider: {provider}. Available providers: {', '.join(get_available_sandbox_types())}"
        raise ValueError(msg)

    sandbox_provider = _SANDBOX_PROVIDERS[provider]

    with sandbox_provider(sandbox_id=sandbox_id, setup_script_path=setup_script_path) as backend:
        yield backend


def get_available_sandbox_types() -> list[str]:
    """Get list of available sandbox provider types.

    Returns:
        List of sandbox type names (e.g., ["modal", "runloop", "docker"])
    """
    return list(_SANDBOX_PROVIDERS.keys())


def get_default_working_dir(provider: str) -> str:
    """Get the default working directory for a given sandbox provider.

    Args:
        provider: Sandbox provider name ("modal", "runloop", "docker")

    Returns:
        Default working directory path as string

    Raises:
        ValueError: If provider is unknown
    """
    if provider in _PROVIDER_TO_WORKING_DIR:
        return _PROVIDER_TO_WORKING_DIR[provider]
    msg = f"Unknown sandbox provider: {provider}"
    raise ValueError(msg)


__all__ = [
    "create_sandbox",
    "create_docker_sandbox",
    "get_available_sandbox_types",
    "get_default_working_dir",
]
