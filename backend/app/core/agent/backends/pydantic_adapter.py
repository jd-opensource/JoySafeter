"""Adapter for pydantic-ai-backend DockerSandbox to SandboxBackendProtocol.

This module provides an adapter layer that bridges pydantic-ai-backend's
DockerSandbox implementation with deepAgents' SandboxBackendProtocol interface.

Supports advanced features from pydantic-ai-backend 0.1.5+:
- RuntimeConfig for pre-configured environments (python-datascience, python-web, etc.)
- session_id for multi-user session management
- idle_timeout for automatic container cleanup
- volumes for Docker volume mounting
"""

import uuid
from datetime import datetime

from deepagents.backends.protocol import (
    EditResult,
    ExecuteResponse,
    FileDownloadResponse,
    FileInfo,
    FileUploadResponse,
    GrepMatch,
    SandboxBackendProtocol,
    WriteResult,
)
from deepagents.backends.utils import format_read_response
from loguru import logger
from pydantic_ai_backends import DockerSandbox

from app.core.agent.backends.constants import (
    DEFAULT_AUTO_REMOVE,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_DOCKER_IMAGE,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_MAX_OUTPUT_SIZE,
    DEFAULT_WORKING_DIR,
)
from app.core.agent.backends.runtime_config import (
    BUILTIN_RUNTIMES,
    RuntimeConfig,
    get_builtin_runtime,
    list_builtin_runtimes,
    resolve_runtime,
)
from app.utils.backend_utils import create_execute_response

# Re-export for backward compatibility
__all__ = [
    "PydanticSandboxAdapter",
    "RuntimeConfig",
    "BUILTIN_RUNTIMES",
    "get_builtin_runtime",
    "list_builtin_runtimes",
]


class PydanticSandboxAdapter(SandboxBackendProtocol):
    """Adapter that wraps pydantic-ai-backend's DockerSandbox for deepAgents.

    This adapter implements SandboxBackendProtocol by delegating to
    pydantic-ai-backend's DockerSandbox, providing a seamless integration
    with deepAgents' FilesystemMiddleware.

    **Lifecycle Management:**
    This adapter follows the pydantic-ai-backend standard lifecycle pattern:
    - `start()` is called automatically in `__init__` to start the container
    - `cleanup()` (or `stop()`) should be called when done to stop the container
    - Both methods are idempotent - safe to call multiple times

    **Features:**
    - Full SandboxBackendProtocol compatibility
    - Delegates to pydantic-ai-backend's DockerSandbox
    - Explicit lifecycle management (start/stop)
    - Automatic resource cleanup
    - Error handling and logging
    - Idempotent start/stop operations
    - RuntimeConfig support for pre-configured environments
    - Session management with session_id
    - Idle timeout for automatic container cleanup
    - Docker volume mounting support

    **Pre-configured Runtimes:**
    - python-minimal: Basic Python 3.12 environment
    - python-datascience: Pandas, NumPy, Matplotlib, Scikit-learn
    - python-web: FastAPI, Uvicorn, SQLAlchemy, httpx
    - python-ml: PyTorch, Transformers
    - node-minimal: Basic Node.js 20 environment
    - node-react: TypeScript, Vite, React

    Example:
        ```python
        from app.core.agent.backends.pydantic_adapter import (
            PydanticSandboxAdapter,
            RuntimeConfig,
        )

        # Basic usage
        adapter = PydanticSandboxAdapter(image="python:3.12-slim")

        # Using pre-configured runtime
        adapter = PydanticSandboxAdapter(runtime="python-datascience")

        # Using custom runtime
        custom_runtime = RuntimeConfig(
            name="ml-env",
            base_image="python:3.12-slim",
            packages=["torch", "transformers"],
        )
        adapter = PydanticSandboxAdapter(runtime=custom_runtime)

        # With session management and volume mounting
        adapter = PydanticSandboxAdapter(
            runtime="python-web",
            session_id="user-123",
            idle_timeout=1800,
            volumes={"/data": "/app/shared"},
        )

        # Use as context manager
        with PydanticSandboxAdapter(runtime="python-minimal") as adapter:
            result = adapter.execute("python --version")
        ```
    """

    def __init__(
        self,
        image: str = DEFAULT_DOCKER_IMAGE,
        working_dir: str = DEFAULT_WORKING_DIR,
        auto_remove: bool = DEFAULT_AUTO_REMOVE,
        max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
        runtime: RuntimeConfig | str | None = None,
        session_id: str | None = None,
        idle_timeout: int = DEFAULT_IDLE_TIMEOUT,
        volumes: dict[str, str] | None = None,
    ):
        """Initialize PydanticSandboxAdapter.

        Creates and starts the Docker sandbox container following the
        pydantic-ai-backend lifecycle pattern. The container is automatically
        started via `start()` method.

        Args:
            image: Docker image to use (default: python:3.12-slim).
                   Ignored if runtime is specified.
            working_dir: Working directory in container
            auto_remove: Auto-remove container on exit
            max_output_size: Maximum command output size in characters
            command_timeout: Command execution timeout in seconds
            runtime: Pre-configured runtime environment. Can be:
                     - str: Name of builtin runtime ("python-datascience", "python-web", etc.)
                     - RuntimeConfig: Custom runtime configuration
                     - None: Use image parameter directly
            session_id: Session identifier for multi-user scenarios.
                        Used to track and potentially reuse sandbox instances.
            idle_timeout: Time in seconds before idle container is cleaned up (default: 3600)
            volumes: Docker volume mappings {host_path: container_path}

        Raises:
            ImportError: If pydantic-ai-backend is not installed
            RuntimeError: If DockerSandbox creation fails

        Note:
            The sandbox container is automatically started during initialization.
            Call `cleanup()` when done to stop and remove the container.

        Example:
            ```python
            # Using builtin runtime
            adapter = PydanticSandboxAdapter(runtime="python-datascience")

            # Using custom runtime
            adapter = PydanticSandboxAdapter(
                runtime=RuntimeConfig(
                    name="custom",
                    base_image="python:3.11",
                    packages=["requests"],
                ),
            )

            # With volumes
            adapter = PydanticSandboxAdapter(
                runtime="python-web",
                volumes={"/host/data": "/container/data"},
            )
            ```
        """

        # Store parameters
        self.runtime = runtime
        self.session_id = session_id
        self.idle_timeout = idle_timeout
        self.volumes = volumes or {}

        # Resolve runtime to get effective image and config
        effective_image, self._runtime_config = resolve_runtime(image, runtime)

        self._id = session_id or str(uuid.uuid4())
        self.image = effective_image
        self.working_dir = working_dir
        self.auto_remove = auto_remove
        self.max_output_size = max_output_size
        self.command_timeout = command_timeout
        self._started = False  # Track sandbox start state

        # Log initialization
        runtime_info = f", runtime={self._runtime_config.name}" if self._runtime_config else ""
        volumes_info = f", volumes={len(self.volumes)}" if self.volumes else ""
        logger.info(
            f"Initializing PydanticSandboxAdapter: id={self._id}, "
            f"image={self.image}, working_dir={working_dir}{runtime_info}{volumes_info}"
        )

        # Prepare runtime parameter for pydantic-ai-backend
        pydantic_runtime = None
        if self._runtime_config:
            pydantic_runtime = self._runtime_config.to_pydantic_runtime()

        # Create DockerSandbox with pydantic-ai-backend API
        try:
            self._sandbox = DockerSandbox(
                image=self.image,
                work_dir=working_dir,
                auto_remove=auto_remove,
                runtime=pydantic_runtime,
                session_id=self.session_id,
                idle_timeout=self.idle_timeout,
                volumes=self.volumes if self.volumes else None,
            )
            logger.info(f"DockerSandbox created: id={self._id}, image={self.image}")
        except Exception as e:
            logger.error(f"Failed to create DockerSandbox for adapter {self._id}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to create DockerSandbox: {e}") from e

        # Start the sandbox
        logger.debug(f"Starting sandbox {self._id}...")
        self.start()

    @property
    def id(self) -> str:
        """Unique identifier for this backend instance."""
        return self._id

    def is_started(self) -> bool:
        """Check if the sandbox container is started.

        Returns:
            True if the sandbox is started, False otherwise.
        """
        return self._started

    def get_runtime_config(self) -> RuntimeConfig | None:
        """获取当前使用的运行时配置。

        Returns:
            RuntimeConfig 实例，如果没有使用运行时配置则返回 None
        """
        return self._runtime_config

    def start(self) -> None:
        """Start the Docker sandbox container. Idempotent - safe to call multiple times."""
        if self._started:
            return

        try:
            if hasattr(self._sandbox, "start"):
                self._sandbox.start()
            self._started = True
            logger.info(f"Sandbox {self._id} started (image={self.image})")
        except Exception as e:
            logger.warning(f"Failed to start sandbox {self._id}: {e}")
            self._started = True  # Mark as started to allow cleanup

    def _exec_command(self, command: str) -> tuple[str, int]:
        """Execute command in sandbox.

        Args:
            command: Shell command to execute

        Returns:
            Tuple of (output, exit_code)
        """
        logger.debug(f"[{self._id}] _exec_command START: {command[:100]}")
        try:
            result = self._sandbox.execute(command)

            # 1. Handle ExecuteResponse from pydantic-ai-backend (output/exit_code/truncated)
            # This is the primary format returned by DockerSandbox.execute()
            if hasattr(result, "output") and hasattr(result, "exit_code"):
                output = result.output if isinstance(result.output, str) else str(result.output or "")
                exit_code = result.exit_code
                logger.debug(f"[{self._id}] _exec_command END: exit_code={exit_code}, output_len={len(output)}")
                return output, exit_code

            # 2. Handle legacy ExecutionResult format (stdout/returncode) - for compatibility
            if hasattr(result, "stdout") and hasattr(result, "returncode"):
                output = (
                    result.stdout.decode("utf-8", errors="replace")
                    if isinstance(result.stdout, bytes)
                    else str(result.stdout or "")
                )
                logger.debug(
                    f"[{self._id}] _exec_command END (legacy): exit_code={result.returncode}, output_len={len(output)}"
                )
                return output, result.returncode

            # 3. Handle dict format (TypedDict or plain dict) - supports both naming conventions
            if isinstance(result, dict):
                output = str(result.get("output", result.get("stdout", "")))
                exit_code_raw = result.get("exit_code", result.get("returncode", 0))
                exit_code = 0
                if exit_code_raw is not None:
                    try:
                        exit_code = int(exit_code_raw)
                    except (TypeError, ValueError):
                        exit_code = 0
                logger.debug(f"[{self._id}] _exec_command END (dict): exit_code={exit_code}, output_len={len(output)}")
                return output, exit_code

            # 4. Fallback - should rarely happen now
            logger.warning(
                f"[{self._id}] _exec_command: unexpected result type {type(result).__name__}, returning as string"
            )
            return str(result) if result else "", 0
        except Exception as e:
            logger.error(f"[{self._id}] _exec_command FAILED: {e}")
            return f"Error: {e}", -1

    # SandboxBackendProtocol implementation

    def ls_info(self, path: str) -> list[FileInfo]:
        """List files and directories in the specified directory.

        Args:
            path: Absolute path to directory.

        Returns:
            List of FileInfo dicts for files and directories.
        """
        try:
            # Use ls command to list files
            output, exit_code = self._exec_command(f"ls -la {path}")
            if exit_code != 0:
                return []

            infos: list[FileInfo] = []
            lines = output.strip().split("\n")[1:]  # Skip "total" line

            for line in lines:
                parts = line.split()
                if len(parts) < 9:
                    continue

                permissions = parts[0]
                size = int(parts[4]) if parts[4].isdigit() else 0
                name = " ".join(parts[8:])

                # Skip . and ..
                if name in (".", ".."):
                    continue

                file_path = f"{path.rstrip('/')}/{name}"
                is_dir = permissions.startswith("d")

                infos.append(
                    {
                        "path": file_path + ("/" if is_dir else ""),
                        "is_dir": is_dir,
                        "size": size,
                        "modified_at": "",
                    }
                )

            return infos

        except Exception as e:
            logger.error(f"Failed to list directory {path}: {e}")
            return []

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file content with line numbers.

        Uses DockerSandbox.read() which leverages Docker's get_archive API
        for reliable file reading with intelligent encoding detection.

        Args:
            file_path: Absolute file path
            offset: Line offset to start reading from (0-indexed)
            limit: Maximum number of lines to read

        Returns:
            Formatted file content with line numbers, or error message.
        """
        logger.info(f"[{self._id}] Reading file: {file_path}")
        try:
            # Use upstream DockerSandbox.read() which uses Docker get_archive API
            # Get full content (large limit) then apply our formatting
            content_raw = self._sandbox.read(file_path, offset=0, limit=100000)
            content = content_raw if isinstance(content_raw, str) else str(content_raw)

            # Check for error from upstream
            if content.startswith("[Error:") or content.startswith("Error:"):
                return content

            # Remove any pagination footer from upstream
            # (e.g., "[... N more lines. Use offset=M to read more.]")
            if "\n\n[..." in content:
                content = content.split("\n\n[...")[0]

            # Format with line numbers using deepagents utility
            lines = content.splitlines()
            file_data = {
                "content": lines,
                "created_at": datetime.now().isoformat(),
                "modified_at": datetime.now().isoformat(),
            }

            result: str = format_read_response(file_data, offset, limit)
            return result
        except Exception as e:
            logger.error(f"[{self._id}] Failed to read file {file_path}: {e}")
            return f"Error: {str(e)}"

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file with content.

        Uses DockerSandbox.write() which leverages Docker's put_archive API
        for reliable file writing without shell command length limits.

        Args:
            file_path: Absolute file path
            content: File content

        Returns:
            WriteResult with success or error.
        """
        logger.info(f"[{self._id}] Writing file: {file_path}")
        try:
            # Check if file already exists
            check_result = self._exec_command(f"test -f {file_path}")
            if check_result[1] == 0:  # exit_code == 0 means file exists
                return WriteResult(
                    error=f"Cannot write to {file_path} because it already exists. "
                    "Read and then make an edit, or write to a new path."
                )

            # Use upstream DockerSandbox.write() which uses Docker put_archive API
            # This handles large files and special characters reliably
            result = self._sandbox.write(file_path, content)

            # Convert upstream WriteResult to deepagents WriteResult
            if hasattr(result, "error") and result.error:
                return WriteResult(error=result.error)
            return WriteResult(path=file_path, files_update=None)
        except Exception as e:
            logger.error(f"[{self._id}] Failed to write file {file_path}: {e}")
            return WriteResult(error=f"Failed to write file: {str(e)}")

    def write_overwrite(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Write a file, overwriting if it already exists.

        Uses DockerSandbox.write() which leverages Docker's put_archive API
        for reliable file writing without shell command length limits.

        Unlike write(), this method does not check if the file exists first.
        Use this for cases where you need to update existing files.

        Args:
            file_path: Absolute file path
            content: File content

        Returns:
            WriteResult with success or error.
        """
        logger.debug(f"[{self._id}] write_overwrite: {file_path}")
        try:
            # Use upstream DockerSandbox.write() which uses Docker put_archive API
            # This handles large files and special characters reliably
            result = self._sandbox.write(file_path, content)

            # Convert upstream WriteResult to deepagents WriteResult
            if hasattr(result, "error") and result.error:
                return WriteResult(error=result.error)
            return WriteResult(path=file_path, files_update=None)
        except Exception as e:
            logger.error(f"[{self._id}] Failed to write file {file_path}: {e}")
            return WriteResult(error=f"Failed to write file: {str(e)}")

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences.

        Uses DockerSandbox.edit() which performs in-memory string replacement
        and writes back using Docker's put_archive API.

        Args:
            file_path: Absolute file path
            old_string: String to replace
            new_string: Replacement string
            replace_all: Replace all occurrences (default: False)

        Returns:
            EditResult with success or error.
        """
        logger.info(f"[{self._id}] Editing file: {file_path}")
        try:
            # Use upstream DockerSandbox.edit() which:
            # 1. Reads file using Docker get_archive API
            # 2. Performs in-memory string replacement
            # 3. Writes back using Docker put_archive API
            result = self._sandbox.edit(file_path, old_string, new_string, replace_all)

            # Convert upstream EditResult to deepagents EditResult
            if hasattr(result, "error") and result.error:
                return EditResult(error=result.error)
            return EditResult(
                path=getattr(result, "path", file_path),
                files_update=None,
                occurrences=getattr(result, "occurrences", 1),
            )
        except Exception as e:
            logger.error(f"[{self._id}] Failed to edit file {file_path}: {e}")
            return EditResult(error=f"Failed to edit file: {str(e)}")

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> list[GrepMatch] | str:
        """Search for a pattern in files.

        Args:
            pattern: Search pattern (literal string)
            path: Directory to search in (default: working_dir)
            glob: Glob pattern to filter files

        Returns:
            List of GrepMatch dicts or error string.
        """
        logger.info(f"[{self._id}] Grepping for pattern: {pattern}")
        search_path = path or self.working_dir
        grep_cmd = f"grep -rn '{pattern}' {search_path}"

        if glob:
            grep_cmd += f" --include='{glob}'"

        output, exit_code = self._exec_command(grep_cmd)

        if exit_code != 0 and not output:
            return []

        matches: list[GrepMatch] = []
        for line in output.strip().split("\n"):
            if not line:
                continue

            parts = line.split(":", 2)
            if len(parts) >= 3:
                matches.append(
                    {
                        "path": parts[0],
                        "line": int(parts[1]) if parts[1].isdigit() else 0,
                        "text": parts[2],
                    }
                )

        return matches

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Find files matching a glob pattern.

        Args:
            pattern: Glob pattern (e.g., "*.py", "**/*.txt")
            path: Directory to search in

        Returns:
            List of FileInfo dicts for matching files.
        """
        logger.info(f"[{self._id}] Globbing for pattern: {pattern}")
        # Use find command with pattern
        find_cmd = f"find {path} -name '{pattern}'"
        output, exit_code = self._exec_command(find_cmd)

        if exit_code != 0:
            return []

        infos: list[FileInfo] = []
        for file_path in output.strip().split("\n"):
            if not file_path:
                continue

            # Get file size
            size_cmd = f"stat -c %s {file_path}"
            size_output, _ = self._exec_command(size_cmd)
            size = int(size_output.strip()) if size_output.strip().isdigit() else 0

            infos.append(
                {
                    "path": file_path,
                    "is_dir": False,
                    "size": size,
                    "modified_at": "",
                }
            )

        return infos

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a shell command in the container.

        Args:
            command: Shell command to execute.

        Returns:
            ExecuteResponse with output, exit code, and truncation flag.
        """
        logger.info(f"[{self._id}] execute() called: {command[:100]}...")
        try:
            # Execute command with timeout
            output, exit_code = self._exec_command(command)

            # Create response with automatic truncation
            response = create_execute_response(
                output=output,
                exit_code=exit_code,
                max_output_size=self.max_output_size,
            )

            if response.truncated:
                logger.debug(
                    f"[{self._id}] Output truncated: {len(output)} -> "
                    f"{len(response.output)} chars (max={self.max_output_size})"
                )

            logger.debug(
                f"[{self._id}] Command execution completed: exit_code={exit_code}, truncated={response.truncated}"
            )
            return response

        except Exception as e:
            logger.error(f"[{self._id}] Error executing command '{command}': {e}", exc_info=True)
            return ExecuteResponse(
                output=f"Error executing command: {str(e)}",
                exit_code=-1,
                truncated=False,
            )

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the Docker sandbox using native API.

        Args:
            paths: List of file paths to download.

        Returns:
            List of FileDownloadResponse objects, one per input path.
        """
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                result = self.execute(f"cat {path}")
                if result.exit_code == 0:
                    responses.append(FileDownloadResponse(path=path, content=result.output.encode("utf-8"), error=None))
                else:
                    responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
            except Exception as e:
                logger.error(f"Failed to download file {path}: {e}")
                responses.append(FileDownloadResponse(path=path, content=None, error="permission_denied"))
        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the Docker sandbox using base64 encoding.

        Args:
            files: List of (path, content) tuples to upload.

        Returns:
            List of FileUploadResponse objects, one per input file.
        """
        import base64

        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                encoded = base64.b64encode(content).decode("ascii")
                _, exit_code = self._exec_command(f"echo '{encoded}' | base64 -d > {path}")
                if exit_code == 0:
                    responses.append(FileUploadResponse(path=path, error=None))
                else:
                    responses.append(FileUploadResponse(path=path, error="permission_denied"))
            except Exception as e:
                logger.error(f"Failed to upload file {path}: {e}")
                responses.append(FileUploadResponse(path=path, error="permission_denied"))
        return responses

    def cleanup(self) -> None:
        """Stop and remove the Docker container. Idempotent - safe to call multiple times."""
        if not self._started:
            return

        try:
            if hasattr(self._sandbox, "stop"):
                self._sandbox.stop()
            elif hasattr(self._sandbox, "cleanup"):
                self._sandbox.cleanup()
            logger.info(f"Sandbox {self._id} stopped")
        except Exception as e:
            logger.warning(f"Failed to stop sandbox {self._id}: {e}")
        finally:
            self._started = False

    def __del__(self):
        """Cleanup on garbage collection."""
        try:
            self.cleanup()
        except Exception:
            pass

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.cleanup()
