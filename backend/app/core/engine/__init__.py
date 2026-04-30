"""
Engine package — unified execution engine abstraction.

Registers all built-in engines at import time.
"""

from app.core.engine.cli_engine import CLIEngine
from app.core.engine.code_engine import CodeEngine
from app.core.engine.copilot_engine import CopilotEngine
from app.core.engine.graph_engine import GraphEngine
from app.core.engine.protocol import EngineCapabilities, ExecutionContext, ExecutionEngine
from app.core.engine.registry import engine_registry

# Register agent runtime engines (user-facing)
engine_registry.register("sandbox", CLIEngine())
engine_registry.register("graph", GraphEngine())
engine_registry.register("code", CodeEngine())

# Register internal platform engines (not user-facing agent runtimes)
engine_registry.register("build_copilot", CopilotEngine())
engine_registry.register("copilot", CopilotEngine())  # backward compat for existing DB rows

__all__ = [
    "ExecutionContext",
    "ExecutionEngine",
    "EngineCapabilities",
    "engine_registry",
    "CLIEngine",
    "CodeEngine",
    "CopilotEngine",
    "GraphEngine",
]
