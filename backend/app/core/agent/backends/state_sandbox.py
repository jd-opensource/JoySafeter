"""StateSandboxBackend: StateBackend with command execution support."""

import subprocess
import uuid
from typing import TYPE_CHECKING

from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol
from deepagents.backends.state import StateBackend

from app.utils.backend_utils import create_execute_response

if TYPE_CHECKING:
    from langchain.tools import ToolRuntime


class StateSandboxBackend(StateBackend, SandboxBackendProtocol):
    """StateBackend with command execution support.

    Extends StateBackend to implement SandboxBackendProtocol by adding
    command execution capabilities. Commands are executed in the local
    system environment.

    Warning:
        This backend executes commands directly on the host system without
        isolation. Use with caution and only with trusted agents. For production
        use, consider using a proper sandboxed backend (e.g., Docker-based).

    Example:
        ```python
        from app.backends.state_sandbox import StateSandboxBackend

        # Use as a factory function
        agent = create_agent(
            model, tools=tools, middleware=[FilesystemMiddleware(backend=lambda rt: StateSandboxBackend(rt))]
        )
        ```
    """

    def __init__(self, runtime: "ToolRuntime", max_output_size: int = 100000):
        """Initialize StateSandboxBackend.

        Args:
            runtime: The tool runtime context.
            max_output_size: Maximum size of command output in characters.
                Output exceeding this limit will be truncated.
        """
        super().__init__(runtime)
        self._id = str(uuid.uuid4())
        self.max_output_size = max_output_size

    @property
    def id(self) -> str:
        """Unique identifier for this backend instance."""
        return self._id

    def execute(self, command: str) -> ExecuteResponse:
        """Execute a shell command.

        Args:
            command: Shell command to execute.

        Returns:
            ExecuteResponse with combined stdout/stderr output and exit code.
        """
        try:
            # Execute command with timeout
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,  # 30 seconds timeout
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
                output="Error: Command execution timed out (30 seconds limit)",
                exit_code=-1,
                truncated=False,
            )
        except Exception as e:
            return ExecuteResponse(
                output=f"Error executing command: {str(e)}",
                exit_code=-1,
                truncated=False,
            )
