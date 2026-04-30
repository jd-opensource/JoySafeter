"""
Engine registry — maps engine_kind to ExecutionEngine instances.
"""

from __future__ import annotations

from app.common.app_errors import NotFoundError
from app.core.engine.protocol import ExecutionEngine


class EngineRegistry:
    """Singleton registry: engine_kind → ExecutionEngine."""

    def __init__(self) -> None:
        self._engines: dict[str, ExecutionEngine] = {}

    def register(self, engine_kind: str, engine: ExecutionEngine) -> None:
        self._engines[engine_kind] = engine

    def has(self, engine_kind: str) -> bool:
        return engine_kind in self._engines

    def get(self, engine_kind: str) -> ExecutionEngine:
        engine = self._engines.get(engine_kind)
        if not engine:
            available = ", ".join(self._engines.keys()) or "(none)"
            raise NotFoundError(
                "Execution engine is not registered",
                code="EXECUTION_ENGINE_NOT_REGISTERED",
                data={"engine_kind": engine_kind, "available_engine_kinds": available},
            )
        return engine

    def list_kinds(self) -> list[str]:
        return list(self._engines.keys())


engine_registry = EngineRegistry()
