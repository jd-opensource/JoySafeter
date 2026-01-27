"""FilesystemSandboxBackend: FilesystemBackend with command execution support."""

import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol

from app.utils.backend_utils import create_execute_response

if TYPE_CHECKING:
    pass


class FilesystemSandboxBackend(FilesystemBackend, SandboxBackendProtocol):
    """FilesystemBackend with command execution support.

    Extends FilesystemBackend to implement SandboxBackendProtocol by adding
    command execution capabilities. Commands are executed in the local system
    environment, with the working directory set to the backend's root_dir.

    Features:
    - ✅ Real filesystem access (read/write actual files)
    - ✅ Command execution in specified directory
    - ✅ Configurable timeout and output limits
    - ✅ Support for virtual_mode (path sandboxing)

    Warning:
        This backend executes commands directly on the host system without
        isolation. Use with caution and only with trusted agents. For production
        use, consider using PydanticSandboxAdapter (Docker sandbox) instead.

    Example:
        ```python
        from app.backends.filesystem_sandbox import FilesystemSandboxBackend

        # Create backend with specific root directory
        backend = FilesystemSandboxBackend(
            root_dir="/path/to/workspace",
            virtual_mode=True,  # Enable path sandboxing
        )

        # Use with Agent
        agent = create_agent(model, tools=tools, middleware=[FilesystemMiddleware(backend=backend)])
        ```
    """

    def __init__(
        self,
        root_dir: str | Path | None = None,
        virtual_mode: bool = False,
        max_file_size_mb: int = 10,
        max_output_size: int = 100000,
        command_timeout: int = 30,
    ):
        """Initialize FilesystemSandboxBackend.

        Args:
            root_dir: Root directory for file operations. If not provided, uses cwd.
            virtual_mode: Enable path sandboxing (prevent access outside root_dir).
            max_file_size_mb: Maximum file size in MB for read operations.
            max_output_size: Maximum command output size in characters.
            command_timeout: Command execution timeout in seconds.
        """
        super().__init__(
            root_dir=root_dir,
            virtual_mode=virtual_mode,
            max_file_size_mb=max_file_size_mb,
        )
        self._id = str(uuid.uuid4())
        self.max_output_size = max_output_size
        self.command_timeout = command_timeout

    @property
    def id(self) -> str:
        """Unique identifier for this backend instance."""
        return self._id

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a shell command in the root directory.

        Args:
            command: Shell command to execute.

        Returns:
            ExecuteResponse with combined stdout/stderr output and exit code.

        Note:
            Commands are executed with cwd set to self.cwd (root_dir).
        """
        try:
            # Execute command with timeout and cwd
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.command_timeout,
                cwd=str(self.cwd),  # Execute in root directory
            )

            # Combine stdout and stderr
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n"
                output += result.stderr

            # Create response with automatic truncation
            return create_execute_response(
                output=output,
                exit_code=result.returncode,
                max_output_size=self.max_output_size,
            )

        except subprocess.TimeoutExpired:
            return ExecuteResponse(
                output=f"Error: Command execution timed out ({self.command_timeout} seconds limit)",
                exit_code=-1,
                truncated=False,
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error executing command: {str(e)}",
                exit_code=-1,
                truncated=False,
            )
