"""
Engine package — unified execution engine abstraction.

Registers all built-in engines at import time.
"""

from app.core.engine.cli_engine import CLIEngine
from app.core.engine.graph_engine import GraphEngine
from app.core.engine.protocol import ExecutionContext, ExecutionEngine
from app.core.engine.registry import engine_registry

# Register built-in engines
engine_registry.register("sandbox", CLIEngine())
engine_registry.register("graph", GraphEngine())

__all__ = [
    "ExecutionContext",
    "ExecutionEngine",
    "engine_registry",
    "CLIEngine",
    "GraphEngine",
]
