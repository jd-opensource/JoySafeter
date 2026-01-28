#!/usr/bin/env python
# coding=utf-8
"""
Base classes and protocols for CodeAgent Python executors.

This module defines the abstract base class and output types for all
Python code executors used by CodeAgent.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger


@dataclass
class CodeOutput:
    """Output from executing Python code."""

    # The result of the last expression evaluated
    output: Any = None

    # Captured print output
    logs: str = ""

    # Whether this execution returned a final answer
    is_final_answer: bool = False

    # Error message if execution failed
    error: str | None = None

    # Execution duration in seconds
    execution_time: float = 0.0

    # Additional metadata
    metadata: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if execution was successful."""
        return self.error is None

    def __str__(self) -> str:
        if self.error:
            return f"Error: {self.error}"
        if self.logs:
            return self.logs.strip()
        return str(self.output) if self.output is not None else ""


class FinalAnswerException(BaseException):
    """
    Exception raised when a final answer is produced.

    This inherits from BaseException (not Exception) so it cannot be
    caught by `except Exception:` blocks in the evaluated code.
    """

    def __init__(self, value: Any):
        self.value = value
        super().__init__(f"FinalAnswer: {value}")


class PythonExecutor(ABC):
    """
    Abstract base class for Python code executors.

    All executors must implement the __call__ method to execute code
    and return a CodeOutput object.
    """

    @abstractmethod
    def send_tools(self, tools: dict[str, Callable]) -> None:
        """
        Send tools to the executor for use in code execution.

        Args:
            tools: Dictionary mapping tool names to callable functions.
        """
        pass

    @abstractmethod
    def send_variables(self, variables: dict[str, Any]) -> None:
        """
        Send variables to the executor's state.

        Args:
            variables: Dictionary mapping variable names to values.
        """
        pass

    @abstractmethod
    def __call__(self, code: str, additional_tools: Optional[dict[str, Callable]] = None) -> CodeOutput:
        """
        Execute Python code and return the output.

        Args:
            code: The Python code to execute.
            additional_tools: Optional additional tools for this execution only.

        Returns:
            CodeOutput containing the result, logs, and status.
        """
        pass

    def reset(self) -> None:
        """Reset the executor state. Override if needed."""
        pass

    def cleanup(self) -> None:
        """Clean up resources. Override if needed."""
        pass

    @staticmethod
    def prepare_code_with_wrapper(
        code: str,
        variables: dict[str, Any],
        final_answer_marker: str = "__FINAL_ANSWER_MARKER__:",
    ) -> str:
        """
        Prepare code for execution by adding variable injection and final_answer wrapper.

        This is a shared utility method used by multiple executor implementations.

        Args:
            code: Original Python code to execute
            variables: Variables to inject into the code execution context
            final_answer_marker: Marker string for final_answer detection

        Returns:
            Prepared code with wrapper that injects variables and defines final_answer()
        """
        import json

        # Serialize variables to JSON
        try:
            variables_json = json.dumps(variables, default=str)
        except Exception as e:
            logger.warning(f"Failed to serialize variables: {e}")
            variables_json = "{}"

        # Create wrapper code
        wrapper = f'''
import json
import sys

# Inject variables
__injected_vars = json.loads('{variables_json}')
for __k, __v in __injected_vars.items():
    globals()[__k] = __v

# Define final_answer function
def final_answer(answer):
    """Return a final answer and terminate execution."""
    print(f"\\n{final_answer_marker} " + json.dumps({{"answer": answer}}, default=str))
    sys.exit(0)

# User code starts here
{code}
'''
        return wrapper


class BaseToolWrapper:
    """Wrapper for making tools compatible with the executor."""

    def __init__(self, tool: Callable, name: Optional[str] = None, description: Optional[str] = None):
        self.tool = tool
        self.name = name or getattr(tool, "__name__", "unknown_tool")
        self.description = description or getattr(tool, "__doc__", "") or ""

    def __call__(self, *args, **kwargs):
        return self.tool(*args, **kwargs)

    def __repr__(self):
        return f"Tool({self.name})"


def wrap_final_answer(original_final_answer: Callable) -> Callable:
    """
    Wrap a final_answer function to raise FinalAnswerException.

    This ensures that when the agent calls final_answer(), execution
    immediately terminates and returns the answer.

    Args:
        original_final_answer: The original final_answer function.

    Returns:
        Wrapped function that raises FinalAnswerException.
    """

    def wrapped_final_answer(*args, **kwargs) -> Any:
        result = original_final_answer(*args, **kwargs)
        raise FinalAnswerException(result)

    wrapped_final_answer.__name__ = "final_answer"
    wrapped_final_answer.__doc__ = original_final_answer.__doc__

    return wrapped_final_answer


__all__ = [
    "CodeOutput",
    "FinalAnswerException",
    "PythonExecutor",
    "BaseToolWrapper",
    "wrap_final_answer",
]
