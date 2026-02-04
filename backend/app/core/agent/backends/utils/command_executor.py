"""Command execution utilities for sandbox backends.

This module provides unified command execution logic that is shared across
different local sandbox backends (FilesystemSandboxBackend, StateSandboxBackend).

Features:
- Unified subprocess execution with timeout support
- Consistent stdout/stderr handling
- Standardized error responses
- Output truncation support
"""

import subprocess
from typing import Optional

from deepagents.backends.protocol import ExecuteResponse

from app.core.agent.backends.constants import (
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_MAX_OUTPUT_SIZE,
)
from app.utils.backend_utils import create_execute_response


def combine_stdout_stderr(stdout: Optional[str], stderr: Optional[str]) -> str:
    """Combine stdout and stderr into a single output string.

    Args:
        stdout: Standard output from command execution
        stderr: Standard error from command execution

    Returns:
        Combined output string with stderr appended after stdout (if both exist)
    """
    output = ""
    if stdout:
        output += stdout
    if stderr:
        if output:
            output += "\n"
        output += stderr
    return output


def create_timeout_error_response(timeout: int) -> ExecuteResponse:
    """Create a standardized timeout error response.

    Args:
        timeout: The timeout value in seconds that was exceeded

    Returns:
        ExecuteResponse with timeout error message
    """
    return ExecuteResponse(
        output=f"Error: Command execution timed out ({timeout} seconds limit)",
        exit_code=-1,
        truncated=False,
    )


def create_error_response(error_message: str) -> ExecuteResponse:
    """Create a standardized error response.

    Args:
        error_message: The error message to include in the response

    Returns:
        ExecuteResponse with error message
    """
    return ExecuteResponse(
        output=f"Error executing command: {error_message}",
        exit_code=-1,
        truncated=False,
    )


def execute_local_command(
    command: str,
    cwd: Optional[str] = None,
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
    max_output_size: int = DEFAULT_MAX_OUTPUT_SIZE,
) -> ExecuteResponse:
    """Execute a shell command locally with unified error handling.

    This function provides a standardized way to execute shell commands
    across different sandbox backends. It handles:
    - Subprocess execution with shell=True
    - Timeout enforcement
    - stdout/stderr combination
    - Output truncation via create_execute_response

    Args:
        command: Shell command to execute
        cwd: Working directory for command execution (None uses current directory)
        timeout: Maximum execution time in seconds (default: 30)
        max_output_size: Maximum output size in characters for truncation (default: 100000)

    Returns:
        ExecuteResponse with combined output, exit code, and truncation flag

    Example:
        >>> result = execute_local_command("ls -la", cwd="/tmp", timeout=10)
        >>> print(result.exit_code)
        0
        >>> print(result.output)
        total 0
        ...
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )

        output = combine_stdout_stderr(result.stdout, result.stderr)

        return create_execute_response(
            output=output,
            exit_code=result.returncode,
            max_output_size=max_output_size,
        )

    except subprocess.TimeoutExpired:
        return create_timeout_error_response(timeout)
    except Exception as e:
        return create_error_response(str(e))
