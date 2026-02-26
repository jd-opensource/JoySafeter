"""Runtime loader for claude-agent-sdk used by Security Dept."""

from __future__ import annotations

import importlib
import sys
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_VENDORED_REPO_DIR = Path(__file__).resolve().parent / "claude-agent-sdk-python"
_VENDORED_SRC_DIR = _VENDORED_REPO_DIR / "src"


@dataclass(frozen=True)
class ClaudeAgentSdkExports:
    """Runtime symbols required by Security Dept."""

    AssistantMessage: type
    ResultMessage: type
    TextBlock: type
    ToolUseBlock: type
    ToolResultBlock: type
    ClaudeAgentOptions: type
    query: Callable[..., AsyncIterator[Any]]


def has_vendored_sdk_source() -> bool:
    """Return whether vendored SDK source exists in this module."""
    init_file = _VENDORED_SRC_DIR / "claude_agent_sdk" / "__init__.py"
    return init_file.exists() and init_file.is_file()


def load_claude_agent_sdk() -> ClaudeAgentSdkExports:
    """Load SDK symbols, preferring vendored source in this module."""
    if has_vendored_sdk_source():
        vendored_src = str(_VENDORED_SRC_DIR)
        if vendored_src not in sys.path:
            sys.path.insert(0, vendored_src)

    sdk = importlib.import_module("claude_agent_sdk")

    return ClaudeAgentSdkExports(
        AssistantMessage=getattr(sdk, "AssistantMessage"),
        ResultMessage=getattr(sdk, "ResultMessage"),
        TextBlock=getattr(sdk, "TextBlock"),
        ToolUseBlock=getattr(sdk, "ToolUseBlock"),
        ToolResultBlock=getattr(sdk, "ToolResultBlock"),
        ClaudeAgentOptions=getattr(sdk, "ClaudeAgentOptions"),
        query=getattr(sdk, "query"),
    )
