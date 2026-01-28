"""
Context Management - Thread-safe context variables for Copilot tools.

Provides per-request isolation for graph context and preloaded models.
"""

import contextvars
from typing import Any, Dict, List

# Thread-safe context variable for graph context (per-request isolation)
_current_graph_context: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar("graph_context", default={})


def set_current_graph_context(context: Dict[str, Any]) -> None:
    """Set the current graph context for analysis tools."""
    _current_graph_context.set(context)


def get_current_graph_context() -> Dict[str, Any]:
    """Get the current graph context from context."""
    return _current_graph_context.get()


# Thread-safe context variable for preloaded models (per-request isolation)
_preloaded_models: contextvars.ContextVar[List[Dict[str, Any]]] = contextvars.ContextVar("preloaded_models", default=[])


def set_preloaded_models(models: List[Dict[str, Any]]) -> None:
    """Set the preloaded models list. Called by agent.py during initialization."""
    _preloaded_models.set(models)


def get_preloaded_models() -> List[Dict[str, Any]]:
    """Get the preloaded models list from context."""
    return _preloaded_models.get()
