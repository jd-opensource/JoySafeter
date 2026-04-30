"""
Engine package — unified execution engine abstraction.

Registers all built-in engines at import time.
"""

from app.core.engine.cli_engine import CLIEngine
from app.core.engine.code_engine import LangGraphCodeEngine
from app.core.engine.copilot_engine import CopilotEngine
from app.core.engine.graph_engine import LangGraphVisualEngine
from app.core.engine.protocol import EngineCapabilities, ExecutionContext, ExecutionEngine
from app.core.engine.registry import engine_registry

engine_registry.register("langgraph_visual", LangGraphVisualEngine())
engine_registry.register("langgraph_code", LangGraphCodeEngine())
engine_registry.register("claude_code", CLIEngine("claude_code"))
engine_registry.register("codex", CLIEngine("codex"))
engine_registry.register("openclaw", CLIEngine("openclaw"))
engine_registry.register("build_copilot", CopilotEngine())

__all__ = [
    "CLIEngine",
    "CopilotEngine",
    "EngineCapabilities",
    "ExecutionContext",
    "ExecutionEngine",
    "LangGraphCodeEngine",
    "LangGraphVisualEngine",
    "engine_registry",
]
