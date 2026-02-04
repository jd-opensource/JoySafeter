"""StateSandboxBackend: StateBackend with command execution support."""

import uuid
from typing import TYPE_CHECKING

from deepagents.backends.protocol import ExecuteResponse, SandboxBackendProtocol
from deepagents.backends.state import StateBackend

from app.core.agent.backends.constants import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_MAX_OUTPUT_SIZE,
)
from app.core.agent.backends.utils.command_executor import execute_local_command

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
        from app.core.agent.backends import StateSandboxBackend

        # Use as a factory function
        agent = create_agent(
            model, tools=tools, middleware=[FilesystemMiddleware(backend=lambda rt: StateSandboxBackend(rt))]
        )
        ```
    """

    def __init__(
        self,
        runtime: "ToolRuntime",
        max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
        command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
    ):
        """Initialize StateSandboxBackend.

        Args:
            runtime: The tool runtime context.
            max_output_size: Maximum size of command output in characters.
                Output exceeding this limit will be truncated.
            command_timeout: Command execution timeout in seconds (default: 30).
        """
        super().__init__(runtime)
        self._id = str(uuid.uuid4())
        self.max_output_size = max_output_size
        self.command_timeout = command_timeout

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
        return execute_local_command(
            command=command,
            cwd=None,  # StateBackend doesn't have a specific working directory
            timeout=self.command_timeout,
            max_output_size=self.max_output_size,
        )
