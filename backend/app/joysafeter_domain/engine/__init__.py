"""
Engine package — unified execution engine abstraction.

Registers all built-in engines at import time.
"""

from app.joysafeter_domain.engine.cli_engine import CLIEngine
from app.joysafeter_domain.engine.code_engine import LangGraphCodeEngine
from app.joysafeter_domain.engine.copilot_engine import CopilotEngine
from app.joysafeter_domain.engine.graph_engine import LangGraphVisualEngine
from app.joysafeter_domain.engine.protocol import EngineCapabilities, ExecutionContext, ExecutionEngine
from app.joysafeter_domain.engine.registry import engine_registry

engine_registry.register("langgraph_visual", LangGraphVisualEngine())
engine_registry.register("langgraph_code", LangGraphCodeEngine())
engine_registry.register("claude_code", CLIEngine("claude_code"))
engine_registry.register("codex", CLIEngine("codex"))
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
