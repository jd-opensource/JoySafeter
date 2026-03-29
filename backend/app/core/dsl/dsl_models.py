"""Intermediate parse structures for the DSL parser."""

from dataclasses import dataclass, field


@dataclass
class ParseError:
    line: int | None
    message: str
    severity: str = "error"  # "error" | "warning"


@dataclass
class ParsedStateField:
    name: str
    field_type: str  # "int", "str", "list", "dict", "messages"
    reducer: str | None  # "add", "append", "merge", None


@dataclass
class ParsedNode:
    var_name: str  # Python variable name (e.g. "classifier")
    node_type: str  # mapped via _FACTORY_TO_NODE_TYPE
    kwargs: dict  # extracted keyword arguments
    inline_code: str | None = None  # for @fn nodes only


@dataclass
class ParsedEdge:
    source: str  # node string name or "START"
    target: str  # node string name or "END"
    route_key: str | None = None  # for conditional edges


@dataclass
class ParseResult:
    state_fields: list[ParsedStateField] = field(default_factory=list)
    nodes: list[ParsedNode] = field(default_factory=list)
    edges: list[ParsedEdge] = field(default_factory=list)
    graph_var: str | None = None
    entry_node: str | None = None
    errors: list[ParseError] = field(default_factory=list)
