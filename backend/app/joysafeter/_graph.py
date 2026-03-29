"""JoyGraph and GraphState base types for the DSL SDK."""

from typing import Any, TypedDict


class GraphState(TypedDict, total=False):
    """Base state class for DSL graphs.

    Users subclass this with their own fields::

        class MyState(GraphState):
            messages: Annotated[list, operator.add]
            score: int
    """

    pass


class JoyGraph:
    """Thin wrapper around LangGraph StateGraph for DSL syntax.

    This class exists so user code has valid imports and IDE autocomplete.
    The backend AST parser reads the code statically — it does not
    instantiate this class at parse time.
    """

    def __init__(self, state_class: type) -> None:
        self.state_class = state_class
        self._nodes: dict[str, Any] = {}
        self._edges: list[tuple] = []

    def add_node(self, name: str, node: Any) -> None:
        self._nodes[name] = node

    def add_edge(self, source: Any, target: Any) -> None:
        self._edges.append((source, target))

    def add_conditional_edges(
        self, source: Any, path_func: Any, path_map: dict[str, Any] | None = None
    ) -> None:
        self._edges.append((source, path_func, path_map))
