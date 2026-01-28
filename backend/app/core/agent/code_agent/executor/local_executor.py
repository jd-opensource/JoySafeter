#!/usr/bin/env python
# coding=utf-8
"""
Local Python Executor for CodeAgent.

This module implements a secure local Python executor using AST interpretation.
It maintains state across executions and supports tool injection.
"""

import ast
import time
from typing import Any, Callable, Optional

from loguru import logger

from ..interpreter import (
    BASE_PYTHON_TOOLS,
    InterpreterError,
    PrintContainer,
    evaluate_ast,
    get_allowed_imports,
)
from .base import CodeOutput, FinalAnswerException, PythonExecutor, wrap_final_answer


def truncate_text(text: str, max_length: int = 50000) -> str:
    """Truncate text if it exceeds max length."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"\n... [{len(text) - max_length} more characters truncated]"


class LocalPythonExecutor(PythonExecutor):
    """
    Secure local Python executor using AST interpretation.

    This executor:
    - Maintains state across multiple code executions
    - Injects tools as callable functions
    - Captures print output
    - Enforces security restrictions
    - Handles FinalAnswerException for termination

    Example:
        >>> executor = LocalPythonExecutor()
        >>> executor.send_tools({"add": lambda a, b: a + b})
        >>> result = executor("x = add(1, 2); print(x)")
        >>> print(result.logs)  # "3\\n"
    """

    def __init__(
        self,
        authorized_imports: Optional[list[str]] = None,
        additional_authorized_imports: Optional[list[str]] = None,
        enable_data_analysis: bool = True,
        max_print_output_length: int = 50000,
    ):
        """
        Initialize the local Python executor.

        Args:
            authorized_imports: Custom list of authorized imports. If None, uses defaults.
            additional_authorized_imports: Additional imports to authorize.
            enable_data_analysis: Enable data analysis modules (pandas, numpy, etc.).
            max_print_output_length: Maximum length of print output before truncation.
        """
        # Build authorized imports list
        if authorized_imports is not None:
            self.authorized_imports = list(authorized_imports)
        else:
            self.authorized_imports = get_allowed_imports(
                base=True,
                data_analysis=enable_data_analysis,
                network=False,
            )

        if additional_authorized_imports:
            self.authorized_imports.extend(additional_authorized_imports)

        # State persists across executions
        self.state: dict[str, Any] = {"__name__": "__main__"}

        # Tools provided via send_tools()
        self.static_tools: dict[str, Callable] = {}

        # User-defined functions (from executed code)
        self.custom_tools: dict[str, Callable] = {}

        self.max_print_output_length = max_print_output_length

        # Initialize with base Python tools
        self._initialize_base_tools()

        logger.info(
            f"LocalPythonExecutor initialized with {len(self.authorized_imports)} authorized imports, "
            f"data_analysis={enable_data_analysis}"
        )

    def _initialize_base_tools(self) -> None:
        """Initialize base Python tools."""
        self.static_tools = {**BASE_PYTHON_TOOLS}  # type: ignore[dict-item]

    def send_tools(self, tools: dict[str, Callable]) -> None:
        """
        Send tools to the executor for use in code execution.

        Args:
            tools: Dictionary mapping tool names to callable functions.
        """
        # Wrap final_answer if present
        for name, func in tools.items():
            if name == "final_answer":
                self.static_tools[name] = wrap_final_answer(func)
            else:
                self.static_tools[name] = func

        logger.debug(f"Injected {len(tools)} tools: {list(tools.keys())}")

    def send_variables(self, variables: dict[str, Any]) -> None:
        """
        Send variables to the executor's state.

        Args:
            variables: Dictionary mapping variable names to values.
        """
        self.state.update(variables)
        logger.debug(f"Updated state with {len(variables)} variables")

    def __call__(
        self,
        code: str,
        additional_tools: Optional[dict[str, Callable]] = None,
    ) -> CodeOutput:
        """
        Execute Python code and return the output.

        Args:
            code: The Python code to execute.
            additional_tools: Optional additional tools for this execution only.

        Returns:
            CodeOutput containing the result, logs, and status.
        """
        start_time = time.time()

        # Prepare print container
        self.state["_print_outputs"] = PrintContainer()
        self.state["_operations_count"] = {"counter": 0}

        # Merge additional tools
        tools = {**self.static_tools}
        if additional_tools:
            for name, func in additional_tools.items():
                if name == "final_answer":
                    tools[name] = wrap_final_answer(func)
                else:
                    tools[name] = func

        try:
            # Parse the code
            try:
                expression = ast.parse(code)
            except SyntaxError as e:
                error_msg = f"SyntaxError: {e.msg} at line {e.lineno}, column {e.offset}"
                return CodeOutput(
                    error=error_msg,
                    execution_time=time.time() - start_time,
                )

            # Evaluate each statement
            result = None
            for node in expression.body:
                try:
                    result = evaluate_ast(
                        node,
                        self.state,
                        tools,
                        self.custom_tools,
                        self.authorized_imports,
                    )
                except FinalAnswerException as e:
                    # Final answer - return immediately
                    logs = str(self.state.get("_print_outputs", ""))
                    return CodeOutput(
                        output=e.value,
                        logs=truncate_text(logs, self.max_print_output_length),
                        is_final_answer=True,
                        execution_time=time.time() - start_time,
                    )

            # Get print outputs
            logs = str(self.state.get("_print_outputs", ""))

            return CodeOutput(
                output=result,
                logs=truncate_text(logs, self.max_print_output_length),
                is_final_answer=False,
                execution_time=time.time() - start_time,
            )

        except InterpreterError as e:
            logs = str(self.state.get("_print_outputs", ""))
            return CodeOutput(
                error=str(e),
                logs=truncate_text(logs, self.max_print_output_length),
                execution_time=time.time() - start_time,
            )

        except Exception as e:
            logs = str(self.state.get("_print_outputs", ""))
            error_msg = f"{type(e).__name__}: {str(e)}"
            logger.exception(f"Error executing code: {error_msg}")
            return CodeOutput(
                error=error_msg,
                logs=truncate_text(logs, self.max_print_output_length),
                execution_time=time.time() - start_time,
            )

    def reset(self) -> None:
        """Reset the executor state."""
        self.state = {"__name__": "__main__"}
        self.custom_tools = {}
        self._initialize_base_tools()
        logger.debug("Executor state reset")

    def get_state_variables(self) -> dict[str, Any]:
        """
        Get user-defined variables from the state.

        Returns:
            Dictionary of user-defined variables (excluding internal ones).
        """
        return {k: v for k, v in self.state.items() if not k.startswith("_") and k != "__name__"}

    def __repr__(self) -> str:
        return (
            f"LocalPythonExecutor("
            f"tools={len(self.static_tools)}, "
            f"custom_tools={len(self.custom_tools)}, "
            f"state_vars={len(self.get_state_variables())}, "
            f"imports={len(self.authorized_imports)}"
            f")"
        )


def create_default_final_answer() -> Callable:
    """Create a default final_answer function."""

    def final_answer(answer: Any) -> Any:
        """
        Return a final answer and terminate execution.

        Args:
            answer: The final answer to return.

        Returns:
            The answer provided.
        """
        return answer

    return final_answer


def create_local_executor(
    tools: Optional[dict[str, Callable]] = None,
    enable_data_analysis: bool = True,
    additional_imports: Optional[list[str]] = None,
) -> LocalPythonExecutor:
    """
    Factory function to create a configured LocalPythonExecutor.

    Args:
        tools: Tools to inject into the executor.
        enable_data_analysis: Enable data analysis modules.
        additional_imports: Additional modules to authorize.

    Returns:
        Configured LocalPythonExecutor instance.
    """
    executor = LocalPythonExecutor(
        enable_data_analysis=enable_data_analysis,
        additional_authorized_imports=additional_imports,
    )

    # Add default final_answer if not provided
    all_tools = {"final_answer": create_default_final_answer()}
    if tools:
        all_tools.update(tools)

    executor.send_tools(all_tools)

    return executor


__all__ = [
    "LocalPythonExecutor",
    "create_local_executor",
    "create_default_final_answer",
    "truncate_text",
]
