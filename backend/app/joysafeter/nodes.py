"""Node factory functions for the DSL SDK.

Each factory returns a ``NodeDef`` marker object that carries the node type
and keyword arguments.  The backend AST parser extracts these statically —
the factories are never called at parse time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class NodeDef:
    """Marker object returned by node factory functions."""

    node_type: str
    kwargs: dict[str, Any] = field(default_factory=dict)


def agent(**kwargs: Any) -> NodeDef:
    return NodeDef(node_type="agent", kwargs=kwargs)


def condition(**kwargs: Any) -> NodeDef:
    return NodeDef(node_type="condition", kwargs=kwargs)


def router(**kwargs: Any) -> NodeDef:
    return NodeDef(node_type="router_node", kwargs=kwargs)


def http(**kwargs: Any) -> NodeDef:
    return NodeDef(node_type="http_request_node", kwargs=kwargs)


def direct_reply(**kwargs: Any) -> NodeDef:
    return NodeDef(node_type="direct_reply", kwargs=kwargs)


def human_input(**kwargs: Any) -> NodeDef:
    return NodeDef(node_type="human_input", kwargs=kwargs)


def tool(**kwargs: Any) -> NodeDef:
    return NodeDef(node_type="tool_node", kwargs=kwargs)


def fn(**kwargs: Any) -> Callable:
    """Decorator factory for inline function nodes.

    Usage::

        @fn(writes=["score"])
        async def scorer(state: MyState):
            return {"score": 85}
    """

    def decorator(func: Callable) -> Callable:
        func._fn_kwargs = kwargs  # type: ignore[attr-defined]
        return func

    return decorator
