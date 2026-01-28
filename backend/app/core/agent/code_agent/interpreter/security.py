#!/usr/bin/env python
# coding=utf-8
"""
Security module for CodeAgent Python interpreter.

This module implements multi-layer security controls:
1. Module whitelist/blacklist
2. Dangerous function detection
3. Import authorization checks
4. Result safety verification
"""

from collections.abc import Callable
from types import BuiltinFunctionType, ModuleType
from typing import Any, Optional

from loguru import logger


class InterpreterError(Exception):
    """Exception raised when there's an error in the interpreter."""

    pass


class SecurityError(InterpreterError):
    """Exception raised when a security violation is detected."""

    pass


# ============================================================================
# Dangerous Modules and Functions
# ============================================================================

# Modules that are never allowed
DANGEROUS_MODULES = [
    "os",
    "subprocess",
    "sys",
    "socket",
    "shutil",
    "pathlib",
    "io",
    "multiprocessing",
    "threading",
    "concurrent",
    "pty",
    "tty",
    "fcntl",
    "signal",
    "resource",
    "gc",
    "ctypes",
    "cffi",
    "importlib",
    "builtins",
    "__builtins__",
    "pip",
    "setuptools",
    "pkg_resources",
    "distutils",
    "code",
    "codeop",
    "compile",
    "ast",
    "inspect",
    "dis",
    "runpy",
    "asyncio.subprocess",
    "webbrowser",
    "antigravity",
    "this",
    "smtplib",
    "smtpd",
    "telnetlib",
    "ftplib",
]

# Specific functions that are dangerous
DANGEROUS_FUNCTIONS = [
    "builtins.compile",
    "builtins.eval",
    "builtins.exec",
    "builtins.execfile",
    "builtins.globals",
    "builtins.locals",
    "builtins.__import__",
    "builtins.open",
    "builtins.input",
    "builtins.breakpoint",
    "builtins.memoryview",
    "os.system",
    "os.popen",
    "os.spawn",
    "os.spawnl",
    "os.spawnle",
    "os.spawnlp",
    "os.spawnlpe",
    "os.spawnv",
    "os.spawnve",
    "os.spawnvp",
    "os.spawnvpe",
    "os.execl",
    "os.execle",
    "os.execlp",
    "os.execlpe",
    "os.execv",
    "os.execve",
    "os.execvp",
    "os.execvpe",
    "os.fork",
    "os.forkpty",
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.Popen",
    "socket.socket",
]

# ============================================================================
# Authorized Imports
# ============================================================================

# Base modules that are always safe to import
BASE_BUILTIN_MODULES = [
    "json",
    "re",
    "math",
    "datetime",
    "time",
    "collections",
    "itertools",
    "functools",
    "random",
    "copy",
    "typing",
    "dataclasses",
    "enum",
    "string",
    "operator",
    "decimal",
    "fractions",
    "statistics",
    "uuid",
    "hashlib",
    "hmac",
    "base64",
    "binascii",
    "textwrap",
    "unicodedata",
    "pprint",
    "heapq",
    "bisect",
    "array",
    "struct",
    "calendar",
    "zoneinfo",
    "contextlib",
    "abc",
    "warnings",
    "numbers",
    "cmath",
    # Sub-modules
    "collections.abc",
    "typing.Union",
    "typing.Optional",
    "typing.List",
    "typing.Dict",
    "typing.Any",
    "typing.Callable",
    "datetime.datetime",
    "datetime.date",
    "datetime.time",
    "datetime.timedelta",
    "functools.wraps",
    "functools.reduce",
    "functools.partial",
    "itertools.chain",
    "itertools.product",
    "itertools.permutations",
    "itertools.combinations",
]

# Data analysis modules (optional, can be enabled)
DATA_ANALYSIS_MODULES = [
    "pandas",
    "pandas.DataFrame",
    "pandas.Series",
    "numpy",
    "numpy.array",
    "numpy.ndarray",
    "matplotlib",
    "matplotlib.pyplot",
    "seaborn",
    "plotly",
    "plotly.express",
    "plotly.graph_objects",
    "scipy",
    "scipy.stats",
    "scipy.optimize",
    "sklearn",
    "sklearn.model_selection",
    "sklearn.preprocessing",
    "sklearn.linear_model",
    "sklearn.tree",
    "sklearn.ensemble",
    "sklearn.cluster",
    "sklearn.metrics",
    "statsmodels",
    "statsmodels.api",
    "PIL",
    "PIL.Image",
    "cv2",
    "openpyxl",
    "xlrd",
    "xlwt",
    "csv",
]

# Network modules (optional, requires explicit permission)
NETWORK_MODULES = [
    "requests",
    "httpx",
    "aiohttp",
    "urllib.parse",
    "urllib.error",
    "http.client",
    "http.server",
]


def check_import_authorized(import_to_check: str, authorized_imports: list[str]) -> bool:
    """
    Check if an import is authorized.

    Args:
        import_to_check: The module/submodule to import.
        authorized_imports: List of authorized import paths.

    Returns:
        True if the import is authorized, False otherwise.
    """
    # Always block dangerous modules
    for dangerous in DANGEROUS_MODULES:
        if import_to_check == dangerous or import_to_check.startswith(f"{dangerous}."):
            logger.warning(f"Blocked dangerous import: {import_to_check}")
            return False

    # Check if module is in the whitelist
    for authorized in authorized_imports:
        # Exact match
        if import_to_check == authorized:
            return True
        # Parent module match (e.g., 'json' authorizes 'json.decoder')
        if import_to_check.startswith(f"{authorized}."):
            return True
        # Child module match (e.g., 'pandas.DataFrame' authorizes 'pandas')
        if authorized.startswith(f"{import_to_check}."):
            return True

    logger.warning(f"Import not authorized: {import_to_check}")
    return False


def check_safer_result(
    result: Any,
    static_tools: dict[str, Callable],
    authorized_imports: list[str],
) -> None:
    """
    Check if the result of an operation is safe.

    Args:
        result: The result to check.
        static_tools: Allowed static tools.
        authorized_imports: List of authorized imports.

    Raises:
        SecurityError: If the result is unsafe.
    """
    # Check for dangerous module access
    if isinstance(result, ModuleType):
        module_name = result.__name__.split(".")[0]
        if module_name in DANGEROUS_MODULES:
            raise SecurityError(f"Access to dangerous module '{module_name}' is forbidden")
        if not check_import_authorized(result.__name__, authorized_imports):
            raise SecurityError(f"Access to unauthorized module '{result.__name__}' is forbidden")

    # Check for dangerous function types
    if isinstance(result, BuiltinFunctionType):
        func_module = getattr(result, "__module__", "") or ""
        func_name = getattr(result, "__name__", "") or ""
        full_name = f"{func_module}.{func_name}"

        if full_name in DANGEROUS_FUNCTIONS:
            raise SecurityError(f"Access to dangerous function '{full_name}' is forbidden")

    # Check for callable with dangerous attributes
    if callable(result) and hasattr(result, "__self__"):
        self_obj = result.__self__
        if isinstance(self_obj, ModuleType):
            module_name = self_obj.__name__.split(".")[0]
            if module_name in DANGEROUS_MODULES:
                raise SecurityError(f"Access to method of dangerous module '{module_name}' is forbidden")


def get_allowed_imports(
    base: bool = True,
    data_analysis: bool = False,
    network: bool = False,
    custom: Optional[list[str]] = None,
) -> list[str]:
    """
    Get the list of allowed imports based on configuration.

    Args:
        base: Include base builtin modules.
        data_analysis: Include data analysis modules (pandas, numpy, etc.).
        network: Include network modules (requests, etc.).
        custom: Additional custom modules to allow.

    Returns:
        List of authorized import paths.
    """
    allowed = []

    if base:
        allowed.extend(BASE_BUILTIN_MODULES)

    if data_analysis:
        allowed.extend(DATA_ANALYSIS_MODULES)

    if network:
        allowed.extend(NETWORK_MODULES)

    if custom:
        allowed.extend(custom)

    return allowed


def is_safe_code(code: str) -> tuple[bool, str | None]:
    """
    Quick static analysis to check if code might be unsafe.

    Args:
        code: The Python code to check.

    Returns:
        Tuple of (is_safe, error_message).
    """
    import re

    # Patterns that indicate potentially dangerous code
    dangerous_patterns = [
        (r"\b__\w+__\b(?!\s*\()", "Access to dunder attributes"),
        (r"\bexec\s*\(", "Use of exec()"),
        (r"\beval\s*\(", "Use of eval()"),
        (r"\bcompile\s*\(", "Use of compile()"),
        (r"\b__import__\s*\(", "Use of __import__()"),
        (r"\bgetattr\s*\([^,]+,\s*['\"]__", "Dunder access via getattr()"),
        (r"\bsetattr\s*\([^,]+,\s*['\"]__", "Dunder access via setattr()"),
        (r"\bglobals\s*\(\)", "Access to globals()"),
        (r"\blocals\s*\(\)", "Access to locals()"),
        (r"\bopen\s*\([^)]*['\"]w", "File write with open()"),
        (r"\bos\s*\.\s*system\s*\(", "Use of os.system()"),
        (r"\bsubprocess\s*\.", "Use of subprocess module"),
        (r"\bsocket\s*\.", "Use of socket module"),
    ]

    for pattern, message in dangerous_patterns:
        if re.search(pattern, code):
            return False, message

    return True, None


def validate_import_statement(code: str, authorized_imports: list[str]) -> tuple[bool, str | None]:
    """
    Validate import statements in code.

    Args:
        code: The Python code to validate.
        authorized_imports: List of authorized imports.

    Returns:
        Tuple of (is_valid, error_message).
    """
    import ast

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True, None  # Let the interpreter handle syntax errors

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not check_import_authorized(alias.name, authorized_imports):
                    return False, f"Import of '{alias.name}' is not allowed"
        elif isinstance(node, ast.ImportFrom):
            if node.module and not check_import_authorized(node.module, authorized_imports):
                return False, f"Import from '{node.module}' is not allowed"

    return True, None


__all__ = [
    "InterpreterError",
    "SecurityError",
    "DANGEROUS_MODULES",
    "DANGEROUS_FUNCTIONS",
    "BASE_BUILTIN_MODULES",
    "DATA_ANALYSIS_MODULES",
    "NETWORK_MODULES",
    "check_import_authorized",
    "check_safer_result",
    "get_allowed_imports",
    "is_safe_code",
    "validate_import_statement",
]
