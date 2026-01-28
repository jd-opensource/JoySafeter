#!/usr/bin/env python
# coding=utf-8
"""
Backend-based Python Executor for CodeAgent.

This module provides a Python executor that uses an existing backend
(e.g., PydanticSandboxAdapter) instead of creating a new container,
allowing code execution to share the same environment as skills and other tools.
"""

import json
import time
from typing import Any, Callable, Optional

from loguru import logger

from .base import CodeOutput, PythonExecutor


class BackendPythonExecutor(PythonExecutor):
    """
    Python executor that uses an existing backend (e.g., PydanticSandboxAdapter).

    This executor reuses an existing backend instead of creating a new container,
    allowing code execution to share the same environment as skills and other tools.

    **Key Benefits:**
    - Resource efficiency: Reuses existing Docker container instead of creating new ones
    - Data persistence: Code execution results persist in the same environment as skills
    - Data sharing: Code can access files created by other nodes or pre-loaded skills
    - Unified lifecycle: Backend lifecycle managed by Graph builder, not executor

    **Lifecycle:**
    - The backend is created by DeepAgentsGraphBuilder and shared across all nodes
    - This executor does NOT manage backend lifecycle (cleanup is handled externally)
    - Code files are written to the shared backend's working directory
    - Temporary code files are cleaned up after execution

    **Features:**
    - ✅ Uses existing backend (no new container created)
    - ✅ Shares file system with skills and other tools
    - ✅ Supports variable injection via send_variables()
    - ✅ Supports final_answer() function for early termination
    - ✅ Proper error handling and logging
    - ✅ Idempotent cleanup (safe to call multiple times)

    Example:
        >>> from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter
        >>> backend = PydanticSandboxAdapter(image="python:3.12-slim")
        >>> executor = BackendPythonExecutor(backend=backend)
        >>> executor.send_variables({"x": 42})
        >>> result = executor("print(f'x = {x}')")
        >>> print(result.logs)  # "x = 42\\n"
    """

    def __init__(self, backend: Any, working_dir: str = "/workspace"):
        """
        Initialize with an existing backend.

        Args:
            backend: Backend instance implementing SandboxBackendProtocol
            working_dir: Working directory in the backend
        """
        self._backend = backend
        self.working_dir = working_dir
        self._variables: dict[str, Any] = {}
        self._tools: dict[str, Callable] = {}
        self.FINAL_ANSWER_MARKER = "__FINAL_ANSWER_MARKER__:"

        backend_id = getattr(backend, "id", "unknown")
        logger.debug(f"BackendPythonExecutor initialized with backend {backend_id}, working_dir={working_dir}")

    def send_tools(self, tools: dict[str, Callable]) -> None:
        """
        Register tools for use in code execution.

        Note: In backend executor, tools are made available as JSON-serializable
        functions that communicate via stdin/stdout.

        Args:
            tools: Dictionary mapping tool names to callable functions.
        """
        self._tools = tools
        logger.debug(f"Registered {len(tools)} tools for BackendPythonExecutor")

    def send_variables(self, variables: dict[str, Any]) -> None:
        """
        Send variables to be available in code execution.

        Note: Variables are serialized to JSON and injected into the code.

        Args:
            variables: Dictionary mapping variable names to values.
        """
        self._variables = variables
        logger.debug(f"Registered {len(variables)} variables for BackendPythonExecutor")

    def _prepare_code(self, code: str) -> str:
        """
        Prepare code for execution in backend.

        Adds:
        - Variable injection
        - final_answer wrapper
        - Output capture

        Args:
            code: Original Python code

        Returns:
            Prepared code with wrapper
        """
        # Use shared utility method from base class
        return PythonExecutor.prepare_code_with_wrapper(
            code=code,
            variables=self._variables,
            final_answer_marker=self.FINAL_ANSWER_MARKER,
        )

    def __call__(
        self,
        code: str,
        additional_tools: Optional[dict[str, Callable]] = None,
    ) -> CodeOutput:
        """
        Execute Python code using the shared backend.

        Args:
            code: The Python code to execute.
            additional_tools: Optional additional tools (not fully supported in backend).

        Returns:
            CodeOutput containing the result, logs, and status.
        """
        start_time = time.time()

        try:
            # Prepare code with wrapper
            prepared_code = self._prepare_code(code)

            # Write code to backend
            code_path = f"{self.working_dir}/code_{int(time.time() * 1000)}.py"
            write_result = self._backend.write(code_path, prepared_code)

            # Unified WriteResult error checking (supports both dict and object formats)
            def get_write_error(wr) -> str | None:
                """Extract error from WriteResult (supports dict or object)."""
                if not wr:
                    return None
                if isinstance(wr, dict):
                    error = wr.get("error")
                    return str(error) if error is not None else None
                elif hasattr(wr, "error"):
                    error = wr.error
                    return str(error) if error is not None else None
                return None

            write_error = get_write_error(write_result)
            if write_error:
                # File might exist, try a new name
                code_path = f"{self.working_dir}/code_{int(time.time() * 1000000)}.py"
                try:
                    self._backend.execute(f"rm -f {code_path}")
                except Exception:
                    pass  # Ignore cleanup errors
                write_result = self._backend.write(code_path, prepared_code)
                write_error = get_write_error(write_result)
                if write_error:
                    return CodeOutput(
                        error=f"Failed to write code: {write_error}",
                        execution_time=time.time() - start_time,
                    )

            # Execute code
            result = self._backend.execute(f"python {code_path}")

            # Handle different result formats (ExecuteResponse, dict, or object)
            # ExecuteResponse has output, exit_code, and truncated attributes
            if isinstance(result, dict):
                output = result.get("output", "")
                exit_code = result.get("exit_code", -1)
            elif hasattr(result, "output") and hasattr(result, "exit_code"):
                # ExecuteResponse object or similar
                output = result.output if result.output else ""
                exit_code = result.exit_code if result.exit_code is not None else -1
            else:
                # Fallback: treat as string output
                output = str(result) if result else ""
                exit_code = 0
                logger.warning(f"Unexpected result format from backend.execute(): {type(result)}")

            # Check for final answer marker
            is_final_answer = False
            final_answer_value = None

            if self.FINAL_ANSWER_MARKER in output:
                is_final_answer = True
                try:
                    # Parse final answer from output
                    marker_pos = output.find(self.FINAL_ANSWER_MARKER)
                    answer_json = output[marker_pos + len(self.FINAL_ANSWER_MARKER) :].strip()
                    # Find the JSON part
                    answer_data = json.loads(answer_json.split("\n")[0])
                    final_answer_value = answer_data.get("answer")
                    # Remove marker from logs
                    output = output[:marker_pos].strip()
                except Exception as e:
                    logger.warning(f"Failed to parse final answer: {e}")

            # Cleanup code file
            try:
                self._backend.execute(f"rm -f {code_path}")
            except Exception as e:
                logger.debug(f"Failed to cleanup code file {code_path}: {e}")

            if exit_code != 0 and not is_final_answer:
                return CodeOutput(
                    error=output if output else f"Execution failed with exit code {exit_code}",
                    logs=output,
                    execution_time=time.time() - start_time,
                )

            return CodeOutput(
                output=final_answer_value if is_final_answer else None,
                logs=output,
                is_final_answer=is_final_answer,
                execution_time=time.time() - start_time,
            )

        except Exception as e:
            logger.exception(f"Backend execution error: {e}")
            return CodeOutput(
                error=str(e),
                execution_time=time.time() - start_time,
            )

    def reset(self) -> None:
        """
        Reset the executor by cleaning up workspace.

        Note: This only cleans the workspace, not the backend itself.
        """
        if self._backend is not None:
            try:
                # Clean workspace (but keep the container running)
                self._backend.execute(f"rm -rf {self.working_dir}/*")
            except Exception as e:
                logger.warning(f"Failed to reset BackendPythonExecutor workspace: {e}")

        self._variables = {}
        logger.debug("BackendPythonExecutor reset")

    def cleanup(self) -> None:
        """
        Cleanup executor resources.

        Note: This is a no-op because the backend is managed externally.
        The backend lifecycle is managed by the Graph builder (DeepAgentsGraphBuilder).

        The shared backend is cleaned up when:
        - Graph execution completes (in API endpoint finally block)
        - Graph building fails (in build() exception handler)
        - Graph is no longer needed (via attached cleanup function)

        This method exists for interface compatibility with PythonExecutor,
        but does not perform any cleanup to avoid interfering with shared backend.
        """
        pass

    def __repr__(self) -> str:
        backend_id = getattr(self._backend, "id", "unknown")
        return f"BackendPythonExecutor(backend_id={backend_id}, working_dir={self.working_dir})"


__all__ = ["BackendPythonExecutor"]
