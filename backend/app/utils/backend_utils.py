"""Backend utilities for common backend operations.

This module provides utility functions for backend implementations,
such as output truncation and response formatting.
"""

from deepagents.backends.protocol import ExecuteResponse


def truncate_output(output: str, max_size: int) -> tuple[str, bool]:
    """Truncate command output if it exceeds the maximum size.

    Args:
        output: Original command output string
        max_size: Maximum output size in characters

    Returns:
        Tuple of (truncated_output, is_truncated)

    Examples:
        >>> truncate_output("short output", 100)
        ('short output', False)
        >>> truncate_output("x" * 200, 100)
        ('x' * 100, True)
    """
    if len(output) > max_size:
        return output[:max_size], True
    return output, False


def create_execute_response(
    output: str,
    exit_code: int,
    max_output_size: int,
    default_output: str = "(no output)",
) -> ExecuteResponse:
    """Create an ExecuteResponse with automatic output truncation.

    This is a convenience function that combines output truncation
    and ExecuteResponse creation, reducing code duplication across
    different backend implementations.

    Args:
        output: Command output string (may be empty)
        exit_code: Command exit code
        max_output_size: Maximum output size before truncation
        default_output: Default output string if output is empty (default: "(no output)")

    Returns:
        ExecuteResponse with truncated output and truncation flag

    Examples:
        >>> response = create_execute_response("output", 0, 100)
        >>> response.exit_code
        0
        >>> response.truncated
        False
        >>> response = create_execute_response("x" * 200, 0, 100)
        >>> response.truncated
        True
    """
    # Use default output if empty
    if not output:
        output = default_output

    # Truncate if necessary
    truncated_output, truncated = truncate_output(output, max_output_size)

    return ExecuteResponse(
        output=truncated_output,
        exit_code=exit_code,
        truncated=truncated,
    )
