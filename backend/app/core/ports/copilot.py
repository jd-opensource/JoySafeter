"""Copilot port — type-safe interface for copilot streaming in core/."""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class CopilotPort(Protocol):
    """Port for copilot graph-building interactions.

    Implemented by: services/copilot_adapter.py
    Used by: core/engine/copilot_engine.py
    """

    async def get_copilot_stream(
        self,
        prompt: str,
        graph_context: Dict[str, Any],
        conversation_history: Optional[List[Dict[str, str]]],
        mode: str,
        graph_id: Optional[str] = None,
    ) -> AsyncIterator[Dict[str, Any]]: ...
