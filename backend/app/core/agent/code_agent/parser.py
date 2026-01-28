#!/usr/bin/env python
# coding=utf-8
"""
Code Parser for CodeAgent.

This module provides utilities for parsing code blocks from LLM outputs
and fixing common issues with generated code.
"""

import re
from typing import Any, Optional


class ParsingError(Exception):
    """Exception raised when code parsing fails."""

    pass


# Regex patterns for code block extraction
CODE_BLOCK_PATTERN = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

# Pattern for extracting thought and code sections
THOUGHT_PATTERN = re.compile(
    r"(?:Thought|思考|分析|想法)[:：]\s*(.*?)(?=(?:Code|代码|```)|$)", re.DOTALL | re.IGNORECASE
)

# Pattern for final_answer calls
FINAL_ANSWER_PATTERN = re.compile(r"final_answer\s*\((.*)\)\s*$", re.DOTALL)


def parse_code_blobs(llm_output: str) -> str:
    """
    Extract Python code from LLM output.

    Handles various formats:
    - Code wrapped in ```python ... ``` blocks
    - Code wrapped in ``` ... ``` blocks
    - Plain code without markers

    Args:
        llm_output: Raw LLM output that may contain code.

    Returns:
        Extracted Python code.

    Raises:
        ParsingError: If no valid code can be extracted.
    """
    if not llm_output or not llm_output.strip():
        raise ParsingError("Empty LLM output - no code to parse")

    # Try to find code blocks with python marker
    matches = CODE_BLOCK_PATTERN.findall(llm_output)
    if matches:
        # Return the last code block (usually the most relevant)
        code: str = str(matches[-1]).strip()
        if code:
            return code

    # Try to find any code block (without language marker)
    generic_pattern = re.compile(r"```\s*\n(.*?)```", re.DOTALL)
    matches = generic_pattern.findall(llm_output)
    if matches:
        code = str(matches[-1]).strip()
        if code:
            return code

    # Check if the entire output looks like code (heuristic)
    lines = llm_output.strip().split("\n")
    code_indicators = [
        "import ",
        "from ",
        "def ",
        "class ",
        "if ",
        "for ",
        "while ",
        "return ",
        "print(",
        "=",
        "#",
        "try:",
        "except:",
        "with ",
    ]

    code_like_lines = sum(1 for line in lines if any(line.strip().startswith(ind) for ind in code_indicators))

    # If more than 50% of lines look like code, treat whole output as code
    if code_like_lines > len(lines) * 0.5:
        return llm_output.strip()

    raise ParsingError(
        "Could not find code block in LLM output. Expected code wrapped in ```python ... ``` or ``` ... ```"
    )


def extract_thought_and_code(llm_output: str) -> tuple[str, str]:
    """
    Extract both thought and code from LLM output.

    Args:
        llm_output: Raw LLM output containing thought and code.

    Returns:
        Tuple of (thought, code).
    """
    thought = ""
    code = ""

    # Try to extract thought section
    thought_match = THOUGHT_PATTERN.search(llm_output)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Extract code
    try:
        code = parse_code_blobs(llm_output)
    except ParsingError:
        # If no code block found, check if there's code after "Code:" marker
        code_marker_pattern = re.compile(r"(?:Code|代码)[:：]\s*(.*)$", re.DOTALL | re.IGNORECASE)
        code_match = code_marker_pattern.search(llm_output)
        if code_match:
            code = code_match.group(1).strip()

    return thought, code


def fix_final_answer_code(code: str) -> str:
    """
    Fix common issues with final_answer code.

    Issues fixed:
    - Missing quotes around string arguments
    - Incorrect function call syntax
    - Adding final_answer wrapper if missing

    Args:
        code: The code that may have issues with final_answer.

    Returns:
        Fixed code.
    """
    # Check if code already has final_answer
    if "final_answer" in code:
        return code

    # If code ends with a simple expression, wrap it in final_answer
    lines = code.strip().split("\n")
    if lines:
        last_line = lines[-1].strip()

        # Check if last line is a simple return or expression
        if last_line.startswith("return "):
            # Convert "return x" to "final_answer(x)"
            value = last_line[7:].strip()
            lines[-1] = f"final_answer({value})"
        elif (
            not last_line.endswith(":")
            and "=" not in last_line
            and not last_line.startswith("#")
            and not last_line.startswith("print(")
            and last_line
        ):
            # Wrap simple expressions
            lines[-1] = f"final_answer({last_line})"

    return "\n".join(lines)


def clean_code(code: str) -> str:
    """
    Clean code by removing unnecessary elements.

    - Removes markdown artifacts
    - Removes leading/trailing whitespace
    - Normalizes newlines

    Args:
        code: The code to clean.

    Returns:
        Cleaned code.
    """
    # Remove markdown artifacts
    code = code.strip()

    # Remove ```python or ``` at start
    if code.startswith("```python"):
        code = code[9:]
    elif code.startswith("```py"):
        code = code[5:]
    elif code.startswith("```"):
        code = code[3:]

    # Remove ``` at end
    if code.endswith("```"):
        code = code[:-3]

    # Remove leading/trailing whitespace again
    code = code.strip()

    # Normalize newlines
    code = code.replace("\r\n", "\n").replace("\r", "\n")

    return code


def validate_python_syntax(code: str) -> tuple[bool, str | None]:
    """
    Validate Python syntax.

    Args:
        code: The code to validate.

    Returns:
        Tuple of (is_valid, error_message).
    """
    import ast

    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"SyntaxError at line {e.lineno}: {e.msg}"


def extract_imports(code: str) -> list[str]:
    """
    Extract import statements from code.

    Args:
        code: The code to analyze.

    Returns:
        List of imported module names.
    """
    import ast

    imports = []
    try:
        tree = ast.parse(code)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module.split(".")[0])
    except SyntaxError:
        # Fallback to regex if parsing fails
        import_pattern = re.compile(r"^\s*(?:from\s+(\S+)|import\s+(\S+))", re.MULTILINE)
        for match in import_pattern.finditer(code):
            module = match.group(1) or match.group(2)
            if module:
                imports.append(module.split(".")[0])

    return list(set(imports))


def format_observation(
    output: Any,
    logs: str = "",
    error: Optional[str] = None,
    max_length: int = 10000,
) -> str:
    """
    Format execution output as an observation string.

    Args:
        output: The output value from execution.
        logs: Captured print output.
        error: Error message if any.
        max_length: Maximum length before truncation.

    Returns:
        Formatted observation string.
    """
    parts = []

    if error:
        parts.append(f"Error: {error}")
    else:
        if logs:
            parts.append(f"Print output:\n{logs.strip()}")

        if output is not None:
            output_str = str(output)
            if len(output_str) > max_length:
                output_str = output_str[:max_length] + "... [truncated]"
            parts.append(f"Result: {output_str}")

    observation = "\n".join(parts) if parts else "Execution completed with no output."

    # Truncate if too long
    if len(observation) > max_length:
        observation = observation[:max_length] + "\n... [output truncated]"

    return observation


def split_code_into_steps(code: str) -> list[str]:
    """
    Split code into logical steps for gradual execution.

    This is useful for debugging and step-by-step execution.

    Args:
        code: The code to split.

    Returns:
        List of code snippets representing logical steps.
    """
    import ast

    steps = []
    try:
        tree = ast.parse(code)
        for node in tree.body:
            step_code = ast.unparse(node)
            steps.append(step_code)
    except SyntaxError:
        # If parsing fails, return the whole code as one step
        steps = [code]

    return steps


__all__ = [
    "ParsingError",
    "parse_code_blobs",
    "extract_thought_and_code",
    "fix_final_answer_code",
    "clean_code",
    "validate_python_syntax",
    "extract_imports",
    "format_observation",
    "split_code_into_steps",
]
