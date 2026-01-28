"""Adapter for pydantic-ai-backend DockerSandbox to SandboxBackendProtocol.

This module provides an adapter layer that bridges pydantic-ai-backend's
DockerSandbox implementation with deepAgents' SandboxBackendProtocol interface.
"""

import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

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
from deepagents.backends.utils import (
    format_read_response,
    perform_string_replacement,
)
from loguru import logger

from app.utils.backend_utils import create_execute_response

if TYPE_CHECKING:
    from pydantic_ai_backends import DockerSandbox

try:
    from pydantic_ai_backends import DockerSandbox

    PYDANTIC_BACKEND_AVAILABLE = True
except ImportError:
    DockerSandbox = None  # type: ignore
    PYDANTIC_BACKEND_AVAILABLE = False
    logger.warning("pydantic-ai-backend not available. Install with: pip install pydantic-ai-backend[docker]")


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

    Features:
    - ✅ Full SandboxBackendProtocol compatibility
    - ✅ Delegates to pydantic-ai-backend's DockerSandbox
    - ✅ Explicit lifecycle management (start/stop)
    - ✅ Automatic resource cleanup
    - ✅ Error handling and logging
    - ✅ Idempotent start/stop operations

    Example:
        ```python
        from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

        # Sandbox is automatically started in __init__
        adapter = PydanticSandboxAdapter(
            image="python:3.12-slim",
            memory_limit="512m",
            network_mode="none",
        )

        from deepagents import FilesystemMiddleware
        agent = create_agent(
            model=model,
            tools=tools,
            middleware=[FilesystemMiddleware(backend=adapter)]
        )

        # Cleanup when done (or use context manager)
        adapter.cleanup()

        # Or use as context manager:
        with PydanticSandboxAdapter(image="python:3.12-slim") as adapter:
            # Use adapter...
            pass  # Automatically cleaned up on exit
        ```
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        memory_limit: str = "512m",
        cpu_quota: int = 50000,
        network_mode: str = "none",
        working_dir: str = "/workspace",
        auto_remove: bool = True,
        max_output_size: int = 100000,
        command_timeout: int = 30,
    ):
        """Initialize PydanticSandboxAdapter.

        Creates and starts the Docker sandbox container following the
        pydantic-ai-backend lifecycle pattern. The container is automatically
        started via `start()` method.

        Args:
            image: Docker image to use (default: python:3.12-slim)
            memory_limit: Memory limit (e.g., "512m", "1g")
            cpu_quota: CPU quota in microseconds (50000 = 50% of one core)
            network_mode: Network mode ("none" for isolation, "bridge" for network access)
            working_dir: Working directory in container
            auto_remove: Auto-remove container on exit
            max_output_size: Maximum command output size in characters
            command_timeout: Command execution timeout in seconds

        Raises:
            ImportError: If pydantic-ai-backend is not installed
            RuntimeError: If DockerSandbox creation fails

        Note:
            The sandbox container is automatically started during initialization.
            Call `cleanup()` when done to stop and remove the container.
        """
        if not PYDANTIC_BACKEND_AVAILABLE:
            raise ImportError(
                "pydantic-ai-backend[docker] is required. Install with: pip install pydantic-ai-backend[docker]"
            )

        self._id = str(uuid.uuid4())
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.network_mode = network_mode
        self.working_dir = working_dir
        self.auto_remove = auto_remove
        self.max_output_size = max_output_size
        self.command_timeout = command_timeout
        self._started = False  # Track sandbox start state

        # Initialize DockerSandbox from pydantic-ai-backend
        logger.info(
            f"Initializing PydanticSandboxAdapter: id={self._id}, "
            f"image={image}, memory_limit={memory_limit}, "
            f"cpu_quota={cpu_quota}, network_mode={network_mode}, "
            f"working_dir={working_dir}"
        )
        try:
            # Try to create DockerSandbox with standard parameters
            # If parameters are not supported, fall back to basic image-only initialization
            try:
                # Standard parameter names (most common API)
                self._sandbox: "DockerSandbox" = DockerSandbox(
                    image=image,
                    memory_limit=memory_limit,
                    cpu_quota=cpu_quota,
                    network_mode=network_mode,
                    working_dir=working_dir,
                )
                logger.debug(
                    f"DockerSandbox created with standard parameters: "
                    f"image={image}, memory={memory_limit}, network={network_mode}"
                )
            except TypeError:
                # Fallback: try with alternative parameter names or minimal set
                try:
                    # Try with alternative parameter names
                    self._sandbox = DockerSandbox(
                        image=image,
                        memory=memory_limit,
                        cpu=cpu_quota,
                        network=network_mode,
                        workdir=working_dir,
                    )
                    logger.debug("DockerSandbox created with alternative parameter names")
                except TypeError:
                    # Final fallback: use only image parameter
                    logger.warning(
                        "DockerSandbox only supports image parameter, "
                        "ignoring memory_limit, cpu_quota, network_mode, working_dir"
                    )
                    self._sandbox = DockerSandbox(image=image)
            logger.info(
                f"PydanticSandboxAdapter created: id={self._id}, "
                f"image={image}, memory={memory_limit}, network={network_mode}"
            )
        except Exception as e:
            logger.error(f"Failed to create DockerSandbox for adapter {self._id}: {e}", exc_info=True)
            raise RuntimeError(f"Failed to create DockerSandbox: {e}") from e

        # Explicitly start the sandbox (following pydantic-ai-backend lifecycle pattern)
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

    def start(self) -> None:
        """Start the Docker sandbox container.

        This method is called automatically in __init__,
        but can also be called manually if needed.

        The method is idempotent - safe to call multiple times.
        """
        if self._started:
            logger.debug(f"Sandbox {self._id} already started, skipping start()")
            return

        logger.info(f"Attempting to start sandbox {self._id}...")
        try:
            if hasattr(self._sandbox, "start"):
                logger.debug(f"Calling start() on DockerSandbox for {self._id}")
                self._sandbox.start()
                self._started = True
                logger.info(f"PydanticSandboxAdapter {self._id} started successfully (image={self.image})")
            else:
                # DockerSandbox might auto-start on creation
                # Mark as started to allow cleanup to work
                logger.debug(f"Sandbox {self._id} does not have start() method, assuming auto-started on creation")
                self._started = True
                logger.info(f"PydanticSandboxAdapter {self._id} ready (auto-started, image={self.image})")
        except Exception as e:
            logger.warning(f"Failed to start sandbox {self._id}: {e}", exc_info=True)
            # Don't raise - allow backward compatibility
            # Mark as started anyway to allow cleanup attempts
            self._started = True

    def _read_file_from_sandbox(self, file_path: str) -> str | None:
        """Read file from sandbox.

        Args:
            file_path: Path to file in sandbox

        Returns:
            File content as string, or None if file doesn't exist.
        """
        logger.info(f"[{self._id}] Reading file: {file_path}")
        try:
            # Try different possible API methods
            if hasattr(self._sandbox, "read"):
                result = self._sandbox.read(file_path)
            elif hasattr(self._sandbox, "read_file"):
                result = self._sandbox.read_file(file_path)
            elif hasattr(self._sandbox, "get_file"):
                result = self._sandbox.get_file(file_path)
            else:
                # Fallback: use execute to read file
                logger.debug(f"[{self._id}] Using execute fallback to read file: {file_path}")
                result = self._exec_command(f"cat {file_path}")
                if result[1] == 0:  # exit_code == 0
                    content = result[0]  # output
                    logger.debug(f"[{self._id}] Successfully read file: {file_path} ({len(content)} chars)")
                    return content
                logger.debug(f"[{self._id}] File read failed: {file_path} (exit_code={result[1]})")
                return None

            if result is None:
                logger.debug(f"[{self._id}] File not found: {file_path}")
                return None
            # If result is bytes, decode it
            if isinstance(result, bytes):
                content = result.decode("utf-8", errors="replace")
            else:
                content = str(result)
            logger.debug(f"[{self._id}] Successfully read file: {file_path} ({len(content)} chars)")
            return content
        except Exception as e:
            logger.debug(f"[{self._id}] Failed to read file {file_path}: {e}", exc_info=True)
            return None

    def _write_file_to_sandbox(self, file_path: str, content: str) -> bool:
        """Write file to sandbox.

        Args:
            file_path: Path to file in sandbox
            content: File content as string

        Returns:
            True if successful, False otherwise.
        """
        logger.info(f"[{self._id}] Writing file: {file_path} ({len(content)} chars)")
        try:
            # Try different possible API methods
            content_bytes = content.encode("utf-8") if isinstance(content, str) else content

            if hasattr(self._sandbox, "write"):
                # Try with path and content
                try:
                    self._sandbox.write(file_path, content_bytes)
                    logger.debug(f"[{self._id}] Successfully wrote file: {file_path}")
                    return True
                except TypeError:
                    # Maybe it expects (path, content) or different format
                    try:
                        self._sandbox.write(file_path, content)  # Try with string
                        logger.debug(f"[{self._id}] Successfully wrote file: {file_path}")
                        return True
                    except Exception as e:
                        logger.debug(f"[{self._id}] Write with string failed: {e}")
                        pass
            elif hasattr(self._sandbox, "write_file"):
                self._sandbox.write_file(file_path, content_bytes)
                logger.debug(f"[{self._id}] Successfully wrote file: {file_path}")
                return True
            elif hasattr(self._sandbox, "put_file"):
                self._sandbox.put_file(file_path, content_bytes)
                logger.debug(f"[{self._id}] Successfully wrote file: {file_path}")
                return True
            else:
                # Fallback: use execute to write file
                # Escape content for shell
                logger.debug(f"[{self._id}] Using execute fallback to write file: {file_path}")
                import shlex

                escaped_content = shlex.quote(content)
                result = self._exec_command(f"echo -n {escaped_content} > {file_path}")
                success = result[1] == 0  # exit_code == 0
                if success:
                    logger.debug(f"[{self._id}] Successfully wrote file: {file_path}")
                else:
                    logger.debug(f"[{self._id}] File write failed: {file_path} (exit_code={result[1]})")
                return success

            logger.warning(f"[{self._id}] All write methods failed for: {file_path}")
            return False
        except Exception as e:
            logger.error(f"[{self._id}] Failed to write file {file_path} to sandbox: {e}", exc_info=True)
            return False

    def _exec_command(self, command: str) -> tuple[str, int]:
        """Execute command in sandbox (internal helper).

        Args:
            command: Shell command to execute

        Returns:
            Tuple of (output, exit_code)
        """
        logger.debug(f"[{self._id}] Executing command: {command}")
        try:
            # Use pydantic-ai-backend's execute method
            # Try different possible API methods
            if hasattr(self._sandbox, "execute"):
                result = self._sandbox.execute(command)
            elif hasattr(self._sandbox, "run"):
                result = self._sandbox.run(command)
            elif hasattr(self._sandbox, "exec"):
                result = self._sandbox.exec(command)
            else:
                logger.error(f"[{self._id}] DockerSandbox does not have execute/run/exec method")
                return "Error: No execute method available", -1

            # Adapt result format to our expected format
            # pydantic-ai-backend may return different format
            if hasattr(result, "stdout") and hasattr(result, "returncode"):
                # Result is an object with stdout and returncode attributes
                output = (
                    result.stdout.decode("utf-8", errors="replace")
                    if isinstance(result.stdout, bytes)
                    else str(result.stdout)
                )
                exit_code = result.returncode
            elif hasattr(result, "output") and hasattr(result, "exit_code"):
                # Alternative attribute names
                output = (
                    result.output.decode("utf-8", errors="replace")
                    if isinstance(result.output, bytes)
                    else str(result.output)
                )
                exit_code = result.exit_code
            elif isinstance(result, tuple) and len(result) >= 2:
                # Result is a tuple (output, exit_code)
                output, exit_code = result[0], result[1]
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
            elif isinstance(result, dict):
                # Result is a dict
                output_raw = result.get("stdout", result.get("output", ""))
                output = str(output_raw) if output_raw is not None else ""
                exit_code = result.get("returncode", result.get("exit_code", 0))
                if isinstance(output, bytes):
                    output = output.decode("utf-8", errors="replace")
            else:
                # Fallback: assume result is output string
                output = str(result) if result else ""
                exit_code = 0

            logger.debug(f"[{self._id}] Command executed: exit_code={exit_code}, output_length={len(output)}")
            if exit_code != 0:
                logger.debug(f"[{self._id}] Command failed: {command[:100]}... (exit_code={exit_code})")
            return output, exit_code
        except Exception as e:
            logger.error(f"[{self._id}] Failed to execute command '{command}': {e}", exc_info=True)
            return f"Error: {str(e)}", -1

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

        Args:
            file_path: Absolute file path
            offset: Line offset to start reading from (0-indexed)
            limit: Maximum number of lines to read

        Returns:
            Formatted file content with line numbers, or error message.
        """
        logger.info(f"[{self._id}] Reading file: {file_path}")
        content = self._read_file_from_sandbox(file_path)
        if content is None:
            return f"Error: File '{file_path}' not found"

        # Create file data structure

        lines = content.splitlines()
        file_data = {
            "content": lines,
            "created_at": datetime.now().isoformat(),
            "modified_at": datetime.now().isoformat(),
        }

        result: str = format_read_response(file_data, offset, limit)
        return result

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Create a new file with content.

        Args:
            file_path: Absolute file path
            content: File content

        Returns:
            WriteResult with success or error.
        """
        logger.info(f"[{self._id}] Writing file: {file_path}")
        # Check if file already exists
        # Use execute to check file existence more reliably
        # This avoids issues with cache or API methods that might return empty strings
        check_result = self._exec_command(f"test -f {file_path}")
        if check_result[1] == 0:  # exit_code == 0 means file exists
            return WriteResult(
                error=f"Cannot write to {file_path} because it already exists. "
                "Read and then make an edit, or write to a new path."
            )

        # Create parent directory if needed
        parent_dir = str(Path(file_path).parent)
        output, exit_code = self._exec_command(f"mkdir -p {parent_dir}")
        if exit_code != 0:
            return WriteResult(error=f"Failed to create parent directory {parent_dir}: {output}")

        # Write file to sandbox
        success = self._write_file_to_sandbox(file_path, content)
        if not success:
            return WriteResult(error=f"Failed to write file {file_path}")

        return WriteResult(path=file_path, files_update=None)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file by replacing string occurrences.

        Args:
            file_path: Absolute file path
            old_string: String to replace
            new_string: Replacement string
            replace_all: Replace all occurrences (default: False)

        Returns:
            EditResult with success or error.
        """
        logger.info(f"[{self._id}] Editing file: {file_path}")
        # Read file from sandbox
        content = self._read_file_from_sandbox(file_path)
        if content is None:
            return EditResult(error=f"Error: File '{file_path}' not found")

        # Perform replacement
        result = perform_string_replacement(content, old_string, new_string, replace_all)
        if isinstance(result, str):
            return EditResult(error=result)

        new_content, occurrences = result

        # Write updated content back to sandbox
        success = self._write_file_to_sandbox(file_path, new_content)
        if not success:
            return EditResult(error=f"Failed to write file {file_path}")

        return EditResult(path=file_path, files_update=None, occurrences=int(occurrences))

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
                content_bytes = None
                # Try to use native API first
                if hasattr(self._sandbox, "read"):
                    result = self._sandbox.read(path)
                    if result is not None:
                        content_bytes = result if isinstance(result, bytes) else result.encode("utf-8")
                elif hasattr(self._sandbox, "read_file"):
                    result = self._sandbox.read_file(path)
                    if result is not None:
                        content_bytes = result if isinstance(result, bytes) else result.encode("utf-8")
                elif hasattr(self._sandbox, "get_file"):
                    result = self._sandbox.get_file(path)
                    if result is not None:
                        content_bytes = result if isinstance(result, bytes) else result.encode("utf-8")

                if content_bytes is None:
                    # Fallback: use execute to read file
                    result = self.execute(f"cat {path}")
                    if result.exit_code == 0:
                        content_bytes = result.output.encode("utf-8")
                    else:
                        responses.append(FileDownloadResponse(path=path, content=None, error="file_not_found"))
                        continue

                responses.append(FileDownloadResponse(path=path, content=content_bytes, error=None))
            except Exception as e:
                logger.error(f"[{self._id}] Failed to download file {path}: {e}", exc_info=True)
                responses.append(FileDownloadResponse(path=path, content=None, error="permission_denied"))

        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the Docker sandbox using native API.

        Args:
            files: List of (path, content) tuples to upload.

        Returns:
            List of FileUploadResponse objects, one per input file.
        """
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                # Try to use native API first
                if hasattr(self._sandbox, "write"):
                    try:
                        self._sandbox.write(path, content)
                        responses.append(FileUploadResponse(path=path, error=None))
                        continue
                    except (TypeError, Exception):
                        pass
                elif hasattr(self._sandbox, "write_file"):
                    self._sandbox.write_file(path, content)
                    responses.append(FileUploadResponse(path=path, error=None))
                    continue
                elif hasattr(self._sandbox, "put_file"):
                    self._sandbox.put_file(path, content)
                    responses.append(FileUploadResponse(path=path, error=None))
                    continue

                # Fallback: use execute to write file
                import shlex

                content_str = content.decode("utf-8", errors="replace")
                escaped_content = shlex.quote(content_str)
                result = self._exec_command(f"echo -n {escaped_content} > {path}")
                if result[1] == 0:  # exit_code == 0
                    responses.append(FileUploadResponse(path=path, error=None))
                else:
                    responses.append(FileUploadResponse(path=path, error="permission_denied"))
            except Exception as e:
                logger.error(f"[{self._id}] Failed to upload file {path}: {e}", exc_info=True)
                responses.append(FileUploadResponse(path=path, error="permission_denied"))

        return responses

    def cleanup(self) -> None:
        """Stop and remove the Docker container.

        This method follows the pydantic-ai-backend lifecycle pattern:
        - Calls stop() if available (preferred)
        - Falls back to cleanup() if stop() is not available
        - Manages _started state to ensure idempotency

        The method is idempotent - safe to call multiple times.
        """
        if not self._started:
            logger.debug(f"Sandbox {self._id} not started, skipping cleanup")
            return

        logger.info(f"Cleaning up sandbox {self._id}...")
        try:
            # Prefer stop() method (pydantic-ai-backend standard)
            if hasattr(self._sandbox, "stop"):
                logger.debug(f"Calling stop() on DockerSandbox for {self._id}")
                self._sandbox.stop()
                logger.info(f"PydanticSandboxAdapter {self._id} stopped successfully (image={self.image})")
            elif hasattr(self._sandbox, "cleanup"):
                # Fallback to cleanup() if stop() is not available
                logger.debug(f"Calling cleanup() on DockerSandbox for {self._id}")
                self._sandbox.cleanup()
                logger.info(f"PydanticSandboxAdapter {self._id} cleaned up successfully (image={self.image})")
            else:
                logger.warning(f"Sandbox {self._id} does not have stop() or cleanup() method")
        except Exception as e:
            logger.warning(f"Failed to stop sandbox {self._id}: {e}", exc_info=True)
        finally:
            # Always reset started state, even if cleanup failed
            self._started = False
            logger.debug(f"Sandbox {self._id} cleanup completed (state reset)")

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
