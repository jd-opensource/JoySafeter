"""Code Executor — execute user LangGraph code in a sandboxed environment.

The executor runs user code via exec() with a whitelist-based import guard.
It extracts the StateGraph instance from the executed code's namespace.

Security model: import whitelist only. Full builtins are available because
TypedDict/Annotated require get_type_hints() to resolve forward references
against the module globals, which breaks with restricted builtins.
"""

from __future__ import annotations

import builtins
import sys
import types
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

# Modules that must NEVER be imported
BLOCKED_MODULES = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests", "httpx",
    "importlib", "ctypes", "signal", "multiprocessing",
    "threading", "asyncio",  # prevent event loop manipulation
    "pickle", "shelve", "marshal",
    "code", "codeop", "compileall",
})

_real_import = builtins.__import__


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    """Import guard: block dangerous modules, allow whitelisted ones."""
    top_level = name.split(".")[0]
    if top_level in BLOCKED_MODULES:
        raise ImportError(
            f"Import of '{name}' is blocked for security reasons."
        )
    if top_level not in ALLOWED_MODULES:
        raise ImportError(
            f"Import of '{name}' is not allowed. "
            f"Allowed: {', '.join(sorted(ALLOWED_MODULES))}"
        )
    return _real_import(name, *args, **kwargs)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def execute_code(code: str) -> StateGraph:
    """Execute user code and return the StateGraph instance.

    The code runs in a synthetic module namespace so that
    ``typing.get_type_hints`` can resolve ``Annotated`` and other
    forward references correctly (it looks up the class's
    ``__module__`` in ``sys.modules``).
    """
    logger.info(f"[CodeExecutor] Executing user code ({len(code)} chars)")

    # Create a synthetic module so get_type_hints can resolve annotations
    module_name = "__langgraph_user_code__"
    module = types.ModuleType(module_name)
    module.__builtins__ = builtins  # full builtins needed for TypedDict
    module.__dict__["__import__"] = _safe_import  # but imports are guarded

    # Temporarily register the module so get_type_hints can find it
    old_module = sys.modules.get(module_name)
    sys.modules[module_name] = module

    try:
        # Patch builtins.__import__ for the duration of exec
        original_import = builtins.__import__
        builtins.__import__ = _safe_import
        try:
            exec(code, module.__dict__)
        finally:
            builtins.__import__ = original_import

        # Find StateGraph instances
        graphs = [
            v for v in module.__dict__.values()
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

    finally:
        # Clean up synthetic module
        if old_module is not None:
            sys.modules[module_name] = old_module
        else:
            sys.modules.pop(module_name, None)

