"""
Engine package — unified execution engine abstraction.

Registers all built-in engines at import time.
"""

from app.core.engine.claude_code_engine import ClaudeCodeEngine
from app.core.engine.codex_engine import CodexEngine
from app.core.engine.code_engine import LangGraphCodeEngine
from app.core.engine.copilot_engine import CopilotEngine
from app.core.engine.graph_engine import LangGraphVisualEngine
from app.core.engine.openclaw_engine import OpenClawEngine
from app.core.engine.protocol import EngineCapabilities, ExecutionContext, ExecutionEngine
from app.core.engine.registry import engine_registry

engine_registry.register("langgraph_visual", LangGraphVisualEngine())
engine_registry.register("langgraph_code", LangGraphCodeEngine())
engine_registry.register("claude_code", ClaudeCodeEngine())
engine_registry.register("codex", CodexEngine())
engine_registry.register("openclaw", OpenClawEngine())
engine_registry.register("build_copilot", CopilotEngine())

__all__ = [
    "ExecutionContext",
    "ExecutionEngine",
    "EngineCapabilities",
    "engine_registry",
    "ClaudeCodeEngine",
    "CodexEngine",
    "CopilotEngine",
    "LangGraphCodeEngine",
    "LangGraphVisualEngine",
    "OpenClawEngine",
]
