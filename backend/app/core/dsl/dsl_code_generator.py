"""DSL Code Generator — convert GraphSchema → DSL-compatible Python code.

The generated code uses the ``joysafeter`` SDK syntax and can be round-tripped
through ``DSLParser.parse_to_schema()`` to produce an equivalent ``GraphSchema``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set

from app.core.graph.graph_schema import (
    EdgeSchema,
    EdgeType,
    GraphSchema,
    NodeSchema,
    ReducerType,
    StateFieldType,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_dsl_code(schema: GraphSchema) -> str:
    """Generate DSL code from a ``GraphSchema``.

    The output is valid DSL that ``DSLParser.parse()`` can round-trip back
    to an equivalent ``GraphSchema``.
    """
    lines: list[str] = []
    lines += _generate_imports(schema)
    lines.append("")
    lines.append("")
    lines += _generate_state_class(schema)
    lines.append("")
    lines += _generate_node_definitions(schema)
    lines.append("")
    lines += _generate_graph_wiring(schema)
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Import generation
# ---------------------------------------------------------------------------

# NodeSchema.type → factory function name
_TYPE_TO_FACTORY: dict[str, str] = {
    "agent": "agent",
    "condition": "condition",
    "router_node": "router",
    "function_node": "fn",
    "http_request_node": "http",
    "direct_reply": "direct_reply",
    "human_input": "human_input",
    "tool_node": "tool",
}


def _generate_imports(schema: GraphSchema) -> list[str]:
    """Generate import statements based on node types used."""
    factory_names: set[str] = set()
    has_fn = False
    for node in schema.nodes:
        factory = _TYPE_TO_FACTORY.get(node.type)
        if factory:
            if factory == "fn":
                has_fn = True
            else:
                factory_names.add(factory)

    # Build node imports
    all_imports = sorted(factory_names)
    if has_fn:
        all_imports.append("fn")

    lines: list[str] = []
    if all_imports:
        lines.append(f"from joysafeter.nodes import {', '.join(all_imports)}")
    lines.append("from joysafeter import JoyGraph, GraphState")
    lines.append("from langgraph.graph import START, END")

    # Check if we need Annotated / operator
    has_reducer = any(
        sf.reducer not in (ReducerType.REPLACE, None)
        for sf in schema.state_fields
    )
    if has_reducer:
        lines.append("from typing import Annotated")
        lines.append("import operator")

    return lines


# ---------------------------------------------------------------------------
# State class generation
# ---------------------------------------------------------------------------

_FIELD_TYPE_TO_STR: dict[StateFieldType, str] = {
    StateFieldType.INT: "int",
    StateFieldType.FLOAT: "float",
    StateFieldType.BOOL: "bool",
    StateFieldType.STRING: "str",
    StateFieldType.LIST: "list",
    StateFieldType.DICT: "dict",
    StateFieldType.MESSAGES: "list",
    StateFieldType.ANY: "dict",
}

_REDUCER_TO_OPERATOR: dict[ReducerType, str] = {
    ReducerType.ADD: "operator.add",
    ReducerType.APPEND: "operator.add",
    ReducerType.ADD_MESSAGES: "operator.add",
}


def _generate_state_class(schema: GraphSchema) -> list[str]:
    """Generate the state class definition."""
    lines: list[str] = []
    lines.append("class MyGraphState(GraphState):")

    if not schema.state_fields:
        lines.append("    messages: Annotated[list, operator.add]")
        return lines

    for sf in schema.state_fields:
        type_str = _FIELD_TYPE_TO_STR.get(sf.field_type, "dict")
        reducer_str = _REDUCER_TO_OPERATOR.get(sf.reducer)

        if reducer_str:
            lines.append(f"    {sf.name}: Annotated[{type_str}, {reducer_str}]")
        else:
            lines.append(f"    {sf.name}: {type_str}")

    return lines


# ---------------------------------------------------------------------------
# Node definition generation
# ---------------------------------------------------------------------------


def _safe_label(label: str) -> str:
    """Convert a node label to a valid Python identifier."""
    name = label.replace(" ", "_").replace("-", "_")
    # Strip non-identifier chars
    name = "".join(c for c in name if c.isalnum() or c == "_")
    if not name or not name[0].isalpha():
        name = "node_" + name
    return name


def _format_kwarg(key: str, value: Any) -> str:
    """Format a keyword argument for a factory call."""
    if isinstance(value, str):
        return f'{key}="{value}"'
    elif isinstance(value, bool):
        return f"{key}={value}"
    elif isinstance(value, (int, float)):
        return f"{key}={value}"
    elif isinstance(value, list):
        return f"{key}={value!r}"
    elif isinstance(value, dict):
        return f"{key}={value!r}"
    else:
        return f"{key}={value!r}"


def _generate_node_definitions(schema: GraphSchema) -> list[str]:
    """Generate node variable definitions."""
    lines: list[str] = []

    for node in schema.nodes:
        factory = _TYPE_TO_FACTORY.get(node.type)
        if not factory:
            lines.append(f"# Unsupported node type: {node.type} (node: {node.label})")
            lines.append("")
            continue

        var_name = _safe_label(node.label)

        if factory == "fn":
            # Emit @fn decorated function
            lines += _generate_fn_node(node, var_name)
        else:
            # Emit factory call
            lines += _generate_factory_node(node, var_name, factory)

        lines.append("")

    return lines


def _generate_factory_node(node: NodeSchema, var_name: str, factory: str) -> list[str]:
    """Generate a factory function call for a node."""
    # Filter config keys to only include relevant ones for each factory
    config = dict(node.config)
    # Remove internal keys that aren't part of the DSL syntax
    internal_keys = {"reads", "writes", "interrupt_before", "interrupt_after", "code"}
    kwargs = {k: v for k, v in config.items() if k not in internal_keys and v is not None}

    if not kwargs:
        return [f"{var_name} = {factory}()"]

    # Format as multi-line if more than 2 kwargs
    if len(kwargs) <= 2:
        args_str = ", ".join(_format_kwarg(k, v) for k, v in kwargs.items())
        return [f"{var_name} = {factory}({args_str})"]

    lines = [f"{var_name} = {factory}("]
    for k, v in kwargs.items():
        lines.append(f"    {_format_kwarg(k, v)},")
    lines.append(")")
    return lines


def _generate_fn_node(node: NodeSchema, var_name: str) -> list[str]:
    """Generate an @fn decorated function node."""
    lines: list[str] = []

    # @fn decorator — no kwargs needed after reads/writes removal
    lines.append("@fn()")

    # Check for inline code
    inline_code = node.config.get("code") or node.config.get("function_code")
    if inline_code and _is_full_function_def(inline_code):
        # The inline code is already a complete function definition
        lines.append(inline_code)
    else:
        # Generate a stub function
        lines.append(f"async def {var_name}(state: MyGraphState):")
        if inline_code:
            # Indent the code body
            for code_line in inline_code.strip().splitlines():
                lines.append(f"    {code_line}")
        else:
            lines.append("    pass")

    return lines


def _is_full_function_def(code: str) -> bool:
    """Check if code is a complete function definition."""
    stripped = code.strip()
    return stripped.startswith("async def ") or stripped.startswith("def ")


# ---------------------------------------------------------------------------
# Graph wiring generation
# ---------------------------------------------------------------------------


def _generate_graph_wiring(schema: GraphSchema) -> list[str]:
    """Generate graph construction and wiring."""
    lines: list[str] = []

    lines.append("g = JoyGraph(MyGraphState)")

    # add_node calls
    for node in schema.nodes:
        var_name = _safe_label(node.label)
        lines.append(f'g.add_node("{node.label}", {var_name})')

    lines.append("")

    # Identify start and end nodes
    incoming: dict[str, set[str]] = {n.id: set() for n in schema.nodes}
    outgoing: dict[str, set[str]] = {n.id: set() for n in schema.nodes}
    for edge in schema.edges:
        if edge.target in incoming:
            incoming[edge.target].add(edge.source)
        if edge.source in outgoing:
            outgoing[edge.source].add(edge.target)

    start_nodes = [n for n in schema.nodes if not incoming[n.id]]
    end_nodes = [n for n in schema.nodes if not outgoing[n.id]]

    # START edges
    for node in start_nodes:
        lines.append(f'g.add_edge(START, "{node.label}")')

    # Normal edges
    conditional_sources: set[str] = set()
    for edge in schema.edges:
        if edge.edge_type == EdgeType.CONDITIONAL:
            conditional_sources.add(edge.source)

    for edge in schema.edges:
        if edge.edge_type == EdgeType.NORMAL:
            lines.append(f'g.add_edge("{edge.source}", "{edge.target}")')

    # Conditional edges — group by source
    cond_edges_by_source: dict[str, list[EdgeSchema]] = {}
    for edge in schema.edges:
        if edge.edge_type == EdgeType.CONDITIONAL:
            cond_edges_by_source.setdefault(edge.source, []).append(edge)

    for source_id, edges in cond_edges_by_source.items():
        source_node = schema.get_node_by_id(source_id)
        source_label = source_node.label if source_node else source_id

        # Build route map
        route_entries: list[str] = []
        for edge in edges:
            target_node = schema.get_node_by_id(edge.target)
            target_label = target_node.label if target_node else edge.target
            route_key = edge.route_key or "default"
            route_entries.append(f'    "{route_key}": "{target_label}",')

        lines.append(
            f'g.add_conditional_edges("{source_label}", '
            f"lambda s: s.get(\"route_decision\"), {{"
        )
        lines.extend(route_entries)
        lines.append("})")

    # END edges
    for node in end_nodes:
        if node.id not in conditional_sources:
            lines.append(f'g.add_edge("{node.label}", END)')

    return lines
