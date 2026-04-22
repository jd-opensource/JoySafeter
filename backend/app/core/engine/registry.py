"""
Engine registry — maps runtime_kind to ExecutionEngine instances.
"""

from __future__ import annotations

from app.core.engine.protocol import ExecutionEngine


class EngineRegistry:
    """Singleton registry: runtime_kind → ExecutionEngine."""

    def __init__(self) -> None:
        self._engines: dict[str, ExecutionEngine] = {}

    def register(self, runtime_kind: str, engine: ExecutionEngine) -> None:
        self._engines[runtime_kind] = engine

    def get(self, runtime_kind: str) -> ExecutionEngine:
        engine = self._engines.get(runtime_kind)
        if not engine:
            available = ", ".join(self._engines.keys()) or "(none)"
            raise ValueError(
                f"No engine registered for runtime_kind={runtime_kind!r}. "
                f"Available: {available}"
            )
        return engine

    def list_kinds(self) -> list[str]:
        return list(self._engines.keys())


engine_registry = EngineRegistry()
