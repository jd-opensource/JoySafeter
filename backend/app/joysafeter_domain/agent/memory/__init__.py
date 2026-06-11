"""
Memory subsystem for the core agent.

Note: Use local/core import paths (app.joysafeter_domain.agent...) instead of the legacy
app.agent... package layout.
"""

from app.joysafeter_domain.schemas.memory import UserMemory

from .manager import MemoryManager
from .strategies import (
    MemoryOptimizationStrategy,
    MemoryOptimizationStrategyFactory,
    MemoryOptimizationStrategyType,
    SummarizeStrategy,
)

__all__ = [
    "MemoryManager",
    "UserMemory",
    "MemoryOptimizationStrategy",
    "MemoryOptimizationStrategyType",
    "MemoryOptimizationStrategyFactory",
    "SummarizeStrategy",
]
