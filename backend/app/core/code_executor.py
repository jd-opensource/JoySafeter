"""Code Executor — execute user LangGraph code in a sandboxed environment.

The executor runs user code via exec() with restricted builtins and
a whitelist-based import guard. It extracts the StateGraph instance
from the executed code's local namespace.
"""

from __future__ import annotations

import builtins
from typing import Any

from langgraph.graph import StateGraph
from loguru import logger


# ---------------------------------------------------------------------------
# Import whitelist
# ---------------------------------------------------------------------------

ALLOWED_MODULES = frozenset({
    # LangGraph / LangChain
    "langgraph", "langchain", "langchain_core", "langchain_community",
    "langchain_openai", "langchain_anthropic", "langchain_google_genai",
    "langchain_deepseek",
    # Python stdlib (safe subset)
    "typing", "typing_extensions", "operator", "functools", "itertools",
    "json", "re", "math", "datetime", "collections", "enum", "dataclasses",
    "abc", "copy", "textwrap", "string", "hashlib", "base64", "uuid",
    # Pydantic
    "pydantic",
})

_real_import = builtins.__import__


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """Import guard that only allows whitelisted top-level modules."""
    top_level = name.split(".")[0]
    if top_level not in ALLOWED_MODULES:
        raise ImportError(
            f"Import of '{name}' is not allowed in code mode. "
            f"Allowed top-level modules: {', '.join(sorted(ALLOWED_MODULES))}"
        )
    return _real_import(name, *args, **kwargs)


# ---------------------------------------------------------------------------
# Safe builtins
# ---------------------------------------------------------------------------

_SAFE_BUILTIN_NAMES = [
    # Types & constructors
    "bool", "int", "float", "str", "bytes", "bytearray",
    "list", "dict", "set", "tuple", "frozenset",
    "type", "object", "property", "classmethod", "staticmethod", "super",
    # Functions
    "print", "len", "range", "enumerate", "zip", "map", "filter",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr", "delattr",
    "callable", "id", "hash", "repr", "format", "chr", "ord",
    "min", "max", "sum", "abs", "round", "pow", "divmod",
    "sorted", "reversed", "any", "all", "iter", "next",
    "input",  # may be needed for human-in-the-loop
    # Constants
    "True", "False", "None", "Ellipsis", "NotImplemented",
    # Exceptions
    "Exception", "BaseException",
    "ValueError", "TypeError", "KeyError", "IndexError",
    "AttributeError", "ImportError", "RuntimeError",
    "StopIteration", "StopAsyncIteration",
    "NotImplementedError", "ZeroDivisionError",
    "FileNotFoundError", "OSError", "IOError",
    "AssertionError", "OverflowError", "RecursionError",
]

_SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(builtins, name)
    for name in _SAFE_BUILTIN_NAMES
    if hasattr(builtins, name)
}
_SAFE_BUILTINS["__import__"] = _safe_import
_SAFE_BUILTINS["__build_class__"] = builtins.__build_class__


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_code(code: str) -> StateGraph:
    """Execute user code and return the StateGraph instance.

    Raises:
        ValueError: if no StateGraph is found or multiple are found.
        SyntaxError: if the code has syntax errors.
        ImportError: if the code tries to import a disallowed module.
        Exception: any runtime error from the user code.
    """
    logger.info(f"[CodeExecutor] Executing user code ({len(code)} chars)")

    sandbox_globals: dict[str, Any] = {"__builtins__": _SAFE_BUILTINS}
    sandbox_locals: dict[str, Any] = {}

    exec(code, sandbox_globals, sandbox_locals)

    # Find StateGraph instances in locals
    graphs = [
        v for v in sandbox_locals.values()
        if isinstance(v, StateGraph)
    ]

    if not graphs:
        raise ValueError(
            "No StateGraph instance found in your code. "
            "Make sure you create a StateGraph variable, e.g.:\n"
            "  graph = StateGraph(MyState)"
        )

    if len(graphs) > 1:
        raise ValueError(
            f"Found {len(graphs)} StateGraph instances. "
            "Only one StateGraph per code file is supported."
        )

    logger.info("[CodeExecutor] StateGraph extracted successfully")
    return graphs[0]
