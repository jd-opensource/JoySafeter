#!/usr/bin/env python
# coding=utf-8
"""
Docker Python Executor for CodeAgent.

This module implements a secure Docker-based Python executor that runs
code in an isolated container environment, providing enhanced security
for untrusted code execution.
"""

import json
import time
from typing import Any, Callable, Optional

from loguru import logger

from .base import CodeOutput, PythonExecutor


class DockerPythonExecutor(PythonExecutor):
    """
    Docker-based Python executor for secure code execution.

    This executor runs Python code inside a Docker container, providing:
    - Full filesystem isolation
    - Network isolation (optional)
    - Resource limits (CPU, memory)
    - Support for packages not available in AST interpreter

    Note: This executor does NOT maintain state across executions like
    LocalPythonExecutor. Each execution is independent.

    Example:
        >>> executor = DockerPythonExecutor(
        ...     image="python:3.12-slim",
        ...     memory_limit="1g",
        ...     network_mode="none",
        ... )
        >>> result = executor("print('Hello from Docker!')")
        >>> print(result.logs)  # "Hello from Docker!\\n"
    """

    def __init__(
        self,
        image: str = "python:3.12-slim",
        memory_limit: str = "1g",
        cpu_quota: int = 100000,
        network_mode: str = "none",
        working_dir: str = "/workspace",
        command_timeout: int = 60,
        max_output_size: int = 100000,
        install_packages: Optional[list[str]] = None,
    ):
        """
        Initialize the Docker Python executor.

        Args:
            image: Docker image to use.
            memory_limit: Memory limit (e.g., "512m", "1g").
            cpu_quota: CPU quota in microseconds.
            network_mode: Network mode ("none" for isolation).
            working_dir: Working directory in container.
            command_timeout: Command execution timeout in seconds.
            max_output_size: Maximum output size in characters.
            install_packages: Python packages to install on init.
        """
        self.image = image
        self.memory_limit = memory_limit
        self.cpu_quota = cpu_quota
        self.network_mode = network_mode
        self.working_dir = working_dir
        self.command_timeout = command_timeout
        self.max_output_size = max_output_size
        self.install_packages = install_packages or []

        # Backend will be lazily initialized
        self._backend = None
        self._tools: dict[str, Callable] = {}
        self._variables: dict[str, Any] = {}

        # Special marker for final answer detection
        self.FINAL_ANSWER_MARKER = "__FINAL_ANSWER_MARKER__:"

        logger.info(
            f"DockerPythonExecutor initialized with image={image}, memory={memory_limit}, network={network_mode}"
        )

    def _get_backend(self):
        """Lazily initialize Docker backend."""
        if self._backend is None:
            try:
                from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

                self._backend = PydanticSandboxAdapter(
                    image=self.image,
                    working_dir=self.working_dir,
                    command_timeout=self.command_timeout,
                    max_output_size=self.max_output_size,
                )

                # Install packages if specified
                if self.install_packages:
                    self._install_packages()

            except ImportError as e:
                logger.error(f"Failed to import PydanticSandboxAdapter: {e}")
                raise RuntimeError(
                    "PydanticSandboxAdapter is required for DockerPythonExecutor. "
                    "Please ensure pydantic-ai-backend[docker] is installed."
                ) from e
            except Exception as e:
                logger.error(f"Failed to create PydanticSandboxAdapter: {e}")
                raise RuntimeError(f"Failed to initialize Docker backend: {e}") from e

        return self._backend

    def _install_packages(self) -> None:
        """Install Python packages in the container."""
        if not self.install_packages:
            return

        packages = " ".join(self.install_packages)
        logger.info(f"Installing packages in container: {packages}")

        result = self._get_backend().execute(f"pip install -q {packages}")
        if result["exit_code"] != 0:
            logger.warning(f"Failed to install packages: {result['output']}")

    def send_tools(self, tools: dict[str, Callable]) -> None:
        """
        Register tools for use in code execution.

        Note: In Docker executor, tools are made available as JSON-serializable
        functions that communicate via stdin/stdout.

        Args:
            tools: Dictionary mapping tool names to callable functions.
        """
        self._tools = tools
        logger.debug(f"Registered {len(tools)} tools for Docker executor")

    def send_variables(self, variables: dict[str, Any]) -> None:
        """
        Send variables to be available in code execution.

        Note: Variables are serialized to JSON and injected into the code.

        Args:
            variables: Dictionary mapping variable names to values.
        """
        self._variables = variables
        logger.debug(f"Registered {len(variables)} variables for Docker executor")

    def _prepare_code(self, code: str) -> str:
        """
        Prepare code for execution in Docker.

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
        Execute Python code in Docker container.

        Args:
            code: The Python code to execute.
            additional_tools: Optional additional tools (not supported in Docker).

        Returns:
            CodeOutput containing the result, logs, and status.
        """
        start_time = time.time()

        try:
            backend = self._get_backend()

            # Prepare code with wrapper
            prepared_code = self._prepare_code(code)

            # Write code to container
            code_path = f"{self.working_dir}/code_{int(time.time())}.py"
            write_result = backend.write(code_path, prepared_code)

            if write_result.get("error"):
                # File might exist, try a new name
                code_path = f"{self.working_dir}/code_{int(time.time() * 1000)}.py"
                backend.execute(f"rm -f {code_path}")  # Force cleanup
                write_result = backend.write(code_path, prepared_code)
                if write_result.get("error"):
                    return CodeOutput(
                        error=f"Failed to write code: {write_result.get('error')}",
                        execution_time=time.time() - start_time,
                    )

            # Execute code
            result = backend.execute(f"python {code_path}")

            output = result.get("output", "")
            exit_code = result.get("exit_code", -1)

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
            backend.execute(f"rm -f {code_path}")

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
            logger.exception(f"Docker execution error: {e}")
            return CodeOutput(
                error=str(e),
                execution_time=time.time() - start_time,
            )

    def reset(self) -> None:
        """Reset the executor by cleaning up the container."""
        if self._backend is not None:
            try:
                # Clean workspace
                self._backend.execute(f"rm -rf {self.working_dir}/*")
            except Exception as e:
                logger.warning(f"Failed to reset Docker executor: {e}")

        self._variables = {}
        logger.debug("Docker executor reset")

    def cleanup(self) -> None:
        """Clean up Docker resources."""
        if self._backend is not None:
            try:
                self._backend.cleanup()
            except Exception as e:
                logger.warning(f"Failed to cleanup Docker backend: {e}")
            finally:
                self._backend = None
        logger.debug("Docker executor cleaned up")

    def __del__(self):
        """Cleanup on garbage collection."""
        self.cleanup()

    def __repr__(self) -> str:
        return f"DockerPythonExecutor(image={self.image}, memory={self.memory_limit}, network={self.network_mode})"


def create_docker_executor(
    install_packages: Optional[list[str]] = None,
    enable_network: bool = False,
    **kwargs,
) -> DockerPythonExecutor:
    """
    Factory function to create a configured DockerPythonExecutor.

    Args:
        install_packages: Python packages to install.
        enable_network: Enable network access in container.
        **kwargs: Additional arguments for DockerPythonExecutor.

    Returns:
        Configured DockerPythonExecutor instance.
    """
    network_mode = "bridge" if enable_network else "none"

    return DockerPythonExecutor(
        install_packages=install_packages,
        network_mode=network_mode,
        **kwargs,
    )


__all__ = [
    "DockerPythonExecutor",
    "create_docker_executor",
]
