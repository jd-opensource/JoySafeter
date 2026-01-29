# Python Coder Tool Implementation
"""
Python Coder Tool - Auto-correcting code execution with ReAct pattern.

This tool generates Python code based on task descriptions, executes it,
and automatically fixes errors through iterative refinement.
"""

import json
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import List, Optional

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from loguru import logger

from app.dynamic_agent.infra.llm import get_default_llm
from dynamic_engine.runtime.command.command_executor import execute_command

from .prompts import CODE_FIX_PROMPT, CODE_GENERATION_PROMPT, PYTHON_CODER_DESCRIPTION

# Constants
MAX_ITERATIONS = 5
TOTAL_TIMEOUT = 300  # 5 minutes
SINGLE_EXECUTION_TIMEOUT = 30
MAX_SAME_ERRORS = 3


class TerminationReason(Enum):
    """Reasons for terminating the ReAct loop."""

    SUCCESS = "success"
    MAX_ITERATIONS = "max_iterations"
    TIMEOUT = "timeout"
    REPEATED_ERROR = "repeated_error"
    UNRECOVERABLE = "unrecoverable"


@dataclass
class IterationLog:
    """Log entry for a single iteration of the ReAct loop."""

    iteration: int
    action: str  # 'generate' or 'fix'
    code_snippet: str  # First 200 chars of code
    result: str  # 'success' or 'error'
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    execution_time_ms: int = 0


@dataclass
class PythonCoderResult:
    """Result of the Python coder tool execution."""

    success: bool
    code: str
    output: str
    error: Optional[str] = None
    iterations: int = 0
    iteration_logs: List[IterationLog] = field(default_factory=list)
    total_time_ms: int = 0
    termination_reason: TerminationReason = TerminationReason.SUCCESS

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        result = asdict(self)
        result["termination_reason"] = self.termination_reason.value
        result["iteration_logs"] = [asdict(log) for log in self.iteration_logs]
        return result


# Unrecoverable error types that cannot be fixed by code changes
UNRECOVERABLE_ERRORS = [
    "PermissionError",
    "FileNotFoundError",
    "ConnectionError",
    "ConnectionRefusedError",
    "TimeoutError",
]


def _parse_error(stderr: str) -> dict:
    """
    Parse Python error information from stderr.

    Args:
        stderr: The stderr output from code execution

    Returns:
        Dictionary with error_type, line_number, message, and is_recoverable
    """
    # Extract error type
    error_match = re.search(r"(\w+Error|\w+Exception):", stderr)
    error_type = error_match.group(1) if error_match else "UnknownError"

    # Extract line number
    line_match = re.search(r"line (\d+)", stderr)
    line_number = int(line_match.group(1)) if line_match else None

    # Check if error is recoverable
    is_recoverable = error_type not in UNRECOVERABLE_ERRORS

    return {"error_type": error_type, "line_number": line_number, "message": stderr, "is_recoverable": is_recoverable}


def _clean_code(code: str) -> str:
    """
    Clean generated code by removing markdown code blocks.

    Args:
        code: Raw code from LLM response

    Returns:
        Cleaned Python code
    """
    code = code.strip()

    # Remove markdown code block markers
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```"):
        code = code[3:]

    if code.endswith("```"):
        code = code[:-3]

    return code.strip()


def _generate_code(task_description: str) -> str:
    """
    Generate Python code using LLM based on task description.

    Args:
        task_description: Description of the task to accomplish

    Returns:
        Generated Python code
    """
    prompt = CODE_GENERATION_PROMPT.format(task_description=task_description)
    response = get_default_llm().invoke([HumanMessage(content=prompt)])
    # Extract content as string - response.content may be str or list
    content_str = response.content if isinstance(response.content, str) else str(response.content)
    return _clean_code(content_str)


def _execute_code(code: str) -> dict:
    """
    Execute Python code by writing to temp file and running with python3.

    Args:
        code: Python code to execute

    Returns:
        Execution result dictionary with stdout, stderr, return_code
    """
    import os
    import tempfile

    try:
        # Write code to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/tmp") as f:
            f.write(code)
            script_path = f.name

        # Execute with python3
        command = f"python3 {script_path}"
        logger.info(f"🐍 Executing: {script_path}")
        result = execute_command(command, timeout=SINGLE_EXECUTION_TIMEOUT)

        # Clean up
        try:
            os.unlink(script_path)
        except OSError as e:
            logger.debug(f"Failed to remove temp script {script_path}: {e}")

        return result
    except Exception as e:
        logger.error(f"💥 Error executing code: {e}")
        return {"stdout": "", "stderr": str(e), "return_code": -1, "error": str(e)}


def _fix_code(code: str, error_info: dict) -> str:
    """
    Fix Python code using LLM based on error information.

    Args:
        code: The original code that failed
        error_info: Dictionary with error_type, line_number, message

    Returns:
        Fixed Python code
    """
    line_info = f"Error line: {error_info['line_number']}" if error_info.get("line_number") else ""

    prompt = CODE_FIX_PROMPT.format(
        code=code,
        error_message=error_info["message"][:1000],  # Truncate long error messages
        error_type=error_info["error_type"],
        line_info=line_info,
    )
    response = get_default_llm().invoke([HumanMessage(content=prompt)])
    # Extract content as string - response.content may be str or list
    content_str = response.content if isinstance(response.content, str) else str(response.content)
    return _clean_code(content_str)


def _check_repeated_errors(error_history: List[str], max_same: int = MAX_SAME_ERRORS) -> bool:
    """
    Check if the same error has occurred consecutively.

    Args:
        error_history: List of error types from previous iterations
        max_same: Maximum allowed consecutive same errors

    Returns:
        True if should terminate due to repeated errors
    """
    if len(error_history) < max_same:
        return False

    recent_errors = error_history[-max_same:]
    return len(set(recent_errors)) == 1


@tool(description=PYTHON_CODER_DESCRIPTION)
def python_coder_tool(task_description: str, max_iterations: int = MAX_ITERATIONS, timeout: int = TOTAL_TIMEOUT) -> str:
    """
    Execute Python code with auto-correction using ReAct pattern.

    This tool generates Python code based on the task description,
    executes it, and automatically fixes errors through iterative refinement.

    Args:
        task_description: Description of the task to accomplish
        max_iterations: Maximum number of retry attempts (default: 5)
        timeout: Total timeout in seconds (default: 300)

    Returns:
        JSON string containing execution result
    """
    start_time = time.time()
    iteration = 0
    code = ""
    error_history: List[str] = []
    iteration_logs: List[IterationLog] = []
    last_error: dict = {}

    logger.info(f"🐍 Python Coder starting: {task_description[:50]}...")

    while True:
        # Check termination conditions
        elapsed_time = time.time() - start_time

        # Timeout check
        if elapsed_time > timeout:
            logger.warning(f"⏰ Python Coder timeout after {elapsed_time:.1f}s")
            result = PythonCoderResult(
                success=False,
                code=code,
                output="",
                error="Total timeout exceeded",
                iterations=iteration,
                iteration_logs=iteration_logs,
                total_time_ms=int(elapsed_time * 1000),
                termination_reason=TerminationReason.TIMEOUT,
            )
            return json.dumps(result.to_dict(), ensure_ascii=False)

        # Max iterations check
        if iteration >= max_iterations:
            logger.warning(f"🔄 Python Coder max iterations reached: {iteration}")
            result = PythonCoderResult(
                success=False,
                code=code,
                output="",
                error="Max iterations exceeded",
                iterations=iteration,
                iteration_logs=iteration_logs,
                total_time_ms=int(elapsed_time * 1000),
                termination_reason=TerminationReason.MAX_ITERATIONS,
            )
            return json.dumps(result.to_dict(), ensure_ascii=False)

        # Repeated error check
        if _check_repeated_errors(error_history):
            logger.warning(f"🔁 Python Coder repeated error: {error_history[-1]}")
            result = PythonCoderResult(
                success=False,
                code=code,
                output="",
                error=f"Repeated error: {error_history[-1]}",
                iterations=iteration,
                iteration_logs=iteration_logs,
                total_time_ms=int(elapsed_time * 1000),
                termination_reason=TerminationReason.REPEATED_ERROR,
            )
            return json.dumps(result.to_dict(), ensure_ascii=False)

        iteration += 1
        iter_start = time.time()

        # Generate or fix code
        try:
            if iteration == 1:
                logger.info(f"📝 Generating code (iteration {iteration})")
                code = _generate_code(task_description)
                action = "generate"
            else:
                logger.info(f"🔧 Fixing code (iteration {iteration})")
                code = _fix_code(code, last_error)
                action = "fix"
        except Exception as e:
            logger.error(f"💥 LLM error: {e}")
            iteration_logs.append(
                IterationLog(
                    iteration=iteration,
                    action="generate" if iteration == 1 else "fix",
                    code_snippet=code[:200] if code else "",
                    result="error",
                    error_type="LLMError",
                    error_message=str(e)[:500],
                    execution_time_ms=int((time.time() - iter_start) * 1000),
                )
            )
            error_history.append("LLMError")
            continue

        # Execute code
        logger.info(f"▶️ Executing code (iteration {iteration})")
        exec_result = _execute_code(code)

        iter_time_ms = int((time.time() - iter_start) * 1000)

        # Check execution result
        if exec_result.get("return_code", -1) == 0:
            logger.info(f"✅ Python Coder success after {iteration} iteration(s)")
            iteration_logs.append(
                IterationLog(
                    iteration=iteration,
                    action=action,
                    code_snippet=code[:200],
                    result="success",
                    execution_time_ms=iter_time_ms,
                )
            )

            result = PythonCoderResult(
                success=True,
                code=code,
                output=exec_result.get("stdout", ""),
                iterations=iteration,
                iteration_logs=iteration_logs,
                total_time_ms=int((time.time() - start_time) * 1000),
                termination_reason=TerminationReason.SUCCESS,
            )
            return json.dumps(result.to_dict(), ensure_ascii=False)

        # Analyze error
        stderr = exec_result.get("stderr", "") or exec_result.get("error", "")
        last_error = _parse_error(stderr)
        error_history.append(last_error["error_type"])

        logger.warning(f"❌ Execution failed: {last_error['error_type']}")

        iteration_logs.append(
            IterationLog(
                iteration=iteration,
                action=action,
                code_snippet=code[:200],
                result="error",
                error_type=last_error["error_type"],
                error_message=last_error["message"][:500],
                execution_time_ms=iter_time_ms,
            )
        )

        # Check if error is recoverable
        if not last_error["is_recoverable"]:
            logger.warning(f"🚫 Unrecoverable error: {last_error['error_type']}")
            result = PythonCoderResult(
                success=False,
                code=code,
                output="",
                error=last_error["message"],
                iterations=iteration,
                iteration_logs=iteration_logs,
                total_time_ms=int((time.time() - start_time) * 1000),
                termination_reason=TerminationReason.UNRECOVERABLE,
            )
            return json.dumps(result.to_dict(), ensure_ascii=False)
