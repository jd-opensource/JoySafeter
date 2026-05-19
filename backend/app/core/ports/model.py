"""Model port — type-safe interface for model resolution in core/."""

from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class ModelPort(Protocol):
    """Port for resolving LLM model instances.

    Implemented by: services/model_service.py (ModelService)
    Used by: core/engine/graph_engine.py, core/graph/deep_agents/model_resolver.py
    """

    async def get_model_instance(
        self, *, user_id: str, provider_name: str, model_name: str,
    ) -> Any: ...

    async def get_runtime_model_by_name(
        self, *, model_name: str, user_id: str,
    ) -> Any: ...
