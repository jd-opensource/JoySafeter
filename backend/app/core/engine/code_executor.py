"""Code Executor — execute user LangGraph code in a sandboxed environment.

Security model:
- Builtins blacklist: open, eval, exec, compile, globals, locals, vars, dir removed
- Import guard: blocklist + allowlist
- Exec timeout: 10 seconds via signal.alarm (Unix)
- TypedDict/Annotated compatibility: uses synthetic module namespace
"""

from __future__ import annotations

import builtins
import signal
import sys
import types
from typing import Any

from langgraph.graph import StateGraph
from loguru import logger

# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

ALLOWED_MODULES = frozenset(
    {
        "langgraph",
        "langchain",
        "langchain_core",
        "langchain_community",
        "langchain_openai",
        "langchain_anthropic",
        "langchain_google_genai",
        "langchain_deepseek",
        "typing",
        "typing_extensions",
        "operator",
        "functools",
        "itertools",
        "json",
        "re",
        "math",
        "datetime",
        "collections",
        "enum",
        "dataclasses",
        "abc",
        "copy",
        "textwrap",
        "string",
        "hashlib",
        "base64",
        "uuid",
        "pydantic",
    }
)

BLOCKED_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
        "socket",
        "http",
        "urllib",
        "requests",
        "httpx",
        "importlib",
        "ctypes",
        "signal",
        "multiprocessing",
        "threading",
        "asyncio",
        "pickle",
        "shelve",
        "marshal",
        "code",
        "codeop",
        "compileall",
        "io",
        "tempfile",
        "glob",
    }
)

_real_import = builtins.__import__


def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
    top_level = name.split(".")[0]
    if top_level in BLOCKED_MODULES:
        raise ImportError(f"Import of '{name}' is blocked for security reasons.")
    if top_level not in ALLOWED_MODULES:
        raise ImportError(f"Import of '{name}' is not allowed. Allowed: {', '.join(sorted(ALLOWED_MODULES))}")
    return _real_import(name, *args, **kwargs)


# ---------------------------------------------------------------------------
# Safe builtins (full builtins minus dangerous functions)
# ---------------------------------------------------------------------------

_BLOCKED_BUILTINS = frozenset(
    {
        "open",
        "eval",
        "exec",
        "compile",
        "globals",
        "locals",
        "vars",
        "dir",
        "breakpoint",
        "exit",
        "quit",
        "__import__",
        "input",  # blocks stdin in server context
    }
)

_safe_builtins = {k: v for k, v in builtins.__dict__.items() if k not in _BLOCKED_BUILTINS}
_safe_builtins["__import__"] = _safe_import

# Exec timeout (seconds)
EXEC_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _timeout_handler(signum: int, frame: Any) -> None:
    raise TimeoutError(f"Code execution timed out ({EXEC_TIMEOUT}s limit)")


def execute_code(code: str) -> StateGraph:
    """Execute user code and return the StateGraph instance.

    Security:
    - Dangerous builtins removed (open, eval, exec, compile, etc.)
    - Import whitelist enforced
    - 10 second execution timeout via SIGALRM
    """
    logger.info(f"[CodeExecutor] Executing user code ({len(code)} chars)")

    # Create synthetic module for TypedDict compatibility
    module_name = "__langgraph_user_code__"
    module = types.ModuleType(module_name)
    module.__dict__["__builtins__"] = _safe_builtins  # restricted builtins
    module.__dict__["__name__"] = module_name

    old_module = sys.modules.get(module_name)
    sys.modules[module_name] = module

    try:
        # Patch builtins.__import__ for duration of exec
        original_import = builtins.__import__
        builtins.__import__ = _safe_import

        # Set exec timeout (Unix only)
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(EXEC_TIMEOUT)

        try:
            exec(code, module.__dict__)
        finally:
            signal.alarm(0)  # cancel timeout
            signal.signal(signal.SIGALRM, old_handler)
            builtins.__import__ = original_import

        # Find StateGraph instances
        graphs = [v for v in module.__dict__.values() if isinstance(v, StateGraph)]

        if not graphs:
            raise ValueError(
                "No StateGraph instance found in your code. "
                "Make sure you create a StateGraph variable, e.g.:\n"
                "  graph = StateGraph(MyState)"
            )

        if len(graphs) > 1:
            raise ValueError(
                f"Found {len(graphs)} StateGraph instances. Only one StateGraph per code file is supported."
            )

        logger.info("[CodeExecutor] StateGraph extracted successfully")
        return graphs[0]

    finally:
        if old_module is not None:
            sys.modules[module_name] = old_module
        else:
            sys.modules.pop(module_name, None)
