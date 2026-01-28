#!/usr/bin/env python
# coding=utf-8
"""
Executor Router for CodeAgent.

This module implements intelligent routing between different Python executors
based on code analysis and security requirements.
"""

import re
from typing import Any, Callable, Optional

from loguru import logger

from .base import CodeOutput, PythonExecutor
from .local_executor import LocalPythonExecutor

# Patterns that indicate potentially dangerous code
DANGEROUS_PATTERNS = [
    # System/OS access
    (r"\bimport\s+os\b", "os module import"),
    (r"\bimport\s+subprocess\b", "subprocess module import"),
    (r"\bimport\s+sys\b", "sys module import"),
    (r"\bimport\s+socket\b", "socket module import"),
    (r"\bimport\s+shutil\b", "shutil module import"),
    # File operations with write mode
    (r"\bopen\s*\([^)]*['\"][wa]", "file write operation"),
    (r"\bopen\s*\([^)]*mode\s*=\s*['\"][wa]", "file write operation"),
    # Network requests
    (r"\brequests\.", "requests library usage"),
    (r"\burllib\.", "urllib library usage"),
    (r"\bhttpx\.", "httpx library usage"),
    (r"\baiohttp\.", "aiohttp library usage"),
    # Code execution
    (r"\beval\s*\(", "eval() call"),
    (r"\bexec\s*\(", "exec() call"),
    (r"\bcompile\s*\(", "compile() call"),
    (r"\b__import__\s*\(", "__import__() call"),
    # Shell commands
    (r"\bos\.system\s*\(", "os.system() call"),
    (r"\bos\.popen\s*\(", "os.popen() call"),
    (r"\bsubprocess\.", "subprocess usage"),
    # Dunder access
    (r"__\w+__\s*(?:\[|\.)", "dunder attribute access"),
    # Pickle (arbitrary code execution)
    (r"\bpickle\.load", "pickle deserialization"),
    (r"\bcPickle\.load", "pickle deserialization"),
]

# Patterns that suggest data analysis (safe for local execution)
DATA_ANALYSIS_PATTERNS = [
    r"\bimport\s+pandas\b",
    r"\bimport\s+numpy\b",
    r"\bimport\s+matplotlib\b",
    r"\bimport\s+seaborn\b",
    r"\bimport\s+sklearn\b",
    r"\bimport\s+scipy\b",
    r"\bpd\.",
    r"\bnp\.",
    r"\bplt\.",
]


class SecurityError(Exception):
    """Exception raised when dangerous code is detected."""

    pass


class ExecutorRouter:
    """
    Routes code execution to appropriate executor based on analysis.

    The router analyzes code to determine:
    1. Is the code safe for local AST interpretation?
    2. Does it require Docker isolation?
    3. Should it be blocked entirely?

    Features:
    - Pattern-based danger detection
    - Configurable routing policies
    - Fallback handling
    - Execution metrics

    Example:
        >>> router = ExecutorRouter(
        ...     local=LocalPythonExecutor(),
        ...     docker=DockerPythonExecutor(),
        ... )
        >>> result = router("import pandas; df = pd.read_csv('data.csv')")
        # Routes to local executor (safe data analysis)

        >>> result = router("import os; os.system('rm -rf /')")
        # Routes to Docker executor (dangerous but allowed in sandbox)
    """

    def __init__(
        self,
        local: Optional[PythonExecutor] = None,
        docker: Optional[PythonExecutor] = None,
        allow_dangerous: bool = False,
        prefer_docker: bool = False,
        dangerous_patterns: Optional[list[tuple[str, str]]] = None,
    ):
        """
        Initialize the executor router.

        Args:
            local: Local Python executor (AST-based).
            docker: Docker Python executor.
            allow_dangerous: Allow dangerous code (routes to Docker).
            prefer_docker: Always prefer Docker when available.
            dangerous_patterns: Custom dangerous patterns to check.
        """
        self.local = local or LocalPythonExecutor()
        self.docker = docker
        self.allow_dangerous = allow_dangerous
        self.prefer_docker = prefer_docker
        self.dangerous_patterns = dangerous_patterns or DANGEROUS_PATTERNS

        # Metrics
        self._local_count = 0
        self._docker_count = 0
        self._blocked_count = 0

        logger.info(
            f"ExecutorRouter initialized: local={type(self.local).__name__}, "
            f"docker={type(self.docker).__name__ if self.docker else 'None'}, "
            f"allow_dangerous={allow_dangerous}"
        )

    def analyze_code(self, code: str) -> dict[str, Any]:
        """
        Analyze code for routing decisions.

        Args:
            code: The Python code to analyze.

        Returns:
            Analysis result with danger level and details.
        """
        dangers = []

        for pattern, description in self.dangerous_patterns:
            if re.search(pattern, code, re.IGNORECASE):
                dangers.append(description)

        # Check for data analysis (considered safe)
        is_data_analysis = any(re.search(pattern, code, re.IGNORECASE) for pattern in DATA_ANALYSIS_PATTERNS)

        return {
            "is_dangerous": len(dangers) > 0,
            "dangers": dangers,
            "is_data_analysis": is_data_analysis,
            "danger_level": len(dangers),
        }

    def route(self, code: str) -> PythonExecutor:
        """
        Determine which executor to use for the code.

        Args:
            code: The Python code to route.

        Returns:
            The appropriate executor.

        Raises:
            SecurityError: If dangerous code is not allowed.
        """
        # Always prefer Docker if configured
        if self.prefer_docker and self.docker is not None:
            logger.debug("Routing to Docker executor (prefer_docker=True)")
            return self.docker  # type: ignore[return-value]

        # Analyze code
        analysis = self.analyze_code(code)

        if analysis["is_dangerous"]:
            dangers = ", ".join(analysis["dangers"])
            logger.warning(f"Dangerous code detected: {dangers}")

            if self.docker is not None:
                logger.info("Routing dangerous code to Docker executor")
                return self.docker  # type: ignore[return-value]
            elif self.allow_dangerous:
                logger.warning("No Docker available, executing dangerous code locally")
                return self.local
            else:
                self._blocked_count += 1
                raise SecurityError(
                    f"Dangerous code patterns detected: {dangers}. "
                    "Configure a Docker executor or set allow_dangerous=True."
                )

        # Safe code - use local executor
        logger.debug("Routing to local executor (safe code)")
        return self.local

    def __call__(
        self,
        code: str,
        additional_tools: Optional[dict[str, Callable]] = None,
    ) -> CodeOutput:
        """
        Execute code using the appropriate executor.

        Args:
            code: The Python code to execute.
            additional_tools: Optional additional tools.

        Returns:
            CodeOutput from the execution.
        """
        try:
            executor = self.route(code)

            if executor is self.local:
                self._local_count += 1
            else:
                self._docker_count += 1

            return executor(code, additional_tools)

        except SecurityError as e:
            return CodeOutput(error=str(e))

    def send_tools(self, tools: dict[str, Callable]) -> None:
        """Send tools to both executors."""
        self.local.send_tools(tools)
        if self.docker:
            self.docker.send_tools(tools)

    def send_variables(self, variables: dict[str, Any]) -> None:
        """Send variables to both executors."""
        self.local.send_variables(variables)
        if self.docker:
            self.docker.send_variables(variables)

    def reset(self) -> None:
        """Reset both executors."""
        self.local.reset()
        if self.docker:
            self.docker.reset()

    def cleanup(self) -> None:
        """Cleanup both executors."""
        self.local.cleanup()
        if self.docker:
            self.docker.cleanup()

    def get_metrics(self) -> dict[str, int]:
        """Get routing metrics."""
        return {
            "local_executions": self._local_count,
            "docker_executions": self._docker_count,
            "blocked_executions": self._blocked_count,
            "total_executions": self._local_count + self._docker_count,
        }

    def __repr__(self) -> str:
        return (
            f"ExecutorRouter("
            f"local={type(self.local).__name__}, "
            f"docker={type(self.docker).__name__ if self.docker else 'None'}, "
            f"metrics={self.get_metrics()}"
            f")"
        )


def create_router(
    enable_docker: bool = True,
    allow_dangerous: bool = False,
    prefer_docker: bool = False,
    docker_kwargs: Optional[dict[Any, Any]] = None,
    local_kwargs: Optional[dict[Any, Any]] = None,
) -> ExecutorRouter:
    """
    Factory function to create a configured ExecutorRouter.

    Args:
        enable_docker: Enable Docker executor.
        allow_dangerous: Allow dangerous code.
        prefer_docker: Always prefer Docker.
        docker_kwargs: Arguments for DockerPythonExecutor.
        local_kwargs: Arguments for LocalPythonExecutor.

    Returns:
        Configured ExecutorRouter instance.
    """
    local = LocalPythonExecutor(**(local_kwargs or {}))

    docker = None
    if enable_docker:
        try:
            from .docker_executor import DockerPythonExecutor

            docker = DockerPythonExecutor(**(docker_kwargs or {}))
        except Exception as e:
            logger.warning(f"Failed to initialize Docker executor: {e}")

    return ExecutorRouter(
        local=local,
        docker=docker,
        allow_dangerous=allow_dangerous,
        prefer_docker=prefer_docker,
    )


__all__ = [
    "SecurityError",
    "ExecutorRouter",
    "create_router",
    "DANGEROUS_PATTERNS",
    "DATA_ANALYSIS_PATTERNS",
]
