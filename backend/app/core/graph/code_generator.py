"""
Code Generator — Generate standalone Python code from a GraphSchema.

Produces a self-contained Python script that recreates the graph using
LangGraph primitives.  The generated code can be run independently of
JoySafeter, making it suitable for:

* Deployment to bare-metal servers
* Sharing graph definitions as code
* Version-controlling graph logic in Git
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

from app.core.graph.graph_schema import (
    GraphSchema,
    ReducerType,
)

# Mapping from schema field types to Python type strings
_PY_TYPE_STR: Dict[str, str] = {
    "string": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "list": "List[Any]",
    "dict": "Dict[str, Any]",
    "messages": "List[BaseMessage]",
    "any": "Any",
}

# Mapping from reducer types to code snippets
_REDUCER_CODE: Dict[str, str] = {
    "replace": "",
    "add": "operator.add",
    "append": "operator.add",
    "merge": "merge_dicts",
    "add_messages": "add_messages",
}


def generate_code(
    schema: GraphSchema,
    *,
    include_main: bool = True,
    include_comments: bool = True,
) -> str:
    """Generate standalone Python code from a ``GraphSchema``.

    Parameters
    ----------
    schema : GraphSchema
        The graph definition to convert to code.
    include_main : bool
        If ``True``, append an ``if __name__ == "__main__"`` block.
    include_comments : bool
        If ``True``, include descriptive comments in the generated code.

    Returns
    -------
    str
        Complete, runnable Python source code.
    """
    lines: List[str] = []

    # -- Header ------------------------------------------------------------
    lines.append('"""')
    lines.append(f"Auto-generated LangGraph workflow: {schema.name}")
    if schema.description:
        lines.append(f"\n{schema.description}")
    lines.append(f"\nGenerated at: {datetime.now(timezone.utc).isoformat()}")
    lines.append('"""')
    lines.append("")

    # -- Imports ------------------------------------------------------------
    lines.append("import operator")
    lines.append("from typing import Any, Annotated, Dict, List, Optional")
    lines.append("")
    lines.append("from langchain_core.messages import AIMessage, BaseMessage, HumanMessage")
    lines.append("from langgraph.graph import END, START, StateGraph")
    lines.append("from typing_extensions import TypedDict")
    lines.append("")
    lines.append("")

    # -- Helper reducers ----------------------------------------------------
    if include_comments:
        lines.append("# --- Reducer helpers ---")
        lines.append("")

    needs_merge = any(sf.reducer == ReducerType.MERGE for sf in schema.state_fields)
    needs_add_messages = any(sf.reducer == ReducerType.ADD_MESSAGES for sf in schema.state_fields)

    if needs_merge:
        lines.append("def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:")
        lines.append('    """Merge two dictionaries, right takes precedence."""')
        lines.append("    result = left.copy() if left else {}")
        lines.append("    if right:")
        lines.append("        result.update(right)")
        lines.append("    return result")
        lines.append("")
        lines.append("")

    if needs_add_messages:
        lines.append("def add_messages(left: List[BaseMessage], right: List[BaseMessage]) -> List[BaseMessage]:")
        lines.append('    """Combine message lists."""')
        lines.append("    return left + right")
        lines.append("")
        lines.append("")

    # -- State class --------------------------------------------------------
    if include_comments:
        lines.append("# --- State definition ---")
        lines.append("")

    if schema.state_fields:
        class_name = f"{schema.name.replace(' ', '')}State"

        if schema.use_default_state:
            lines.append(f"class {class_name}(TypedDict, total=False):")
        else:
            lines.append(f"class {class_name}(TypedDict, total=False):")

        if schema.description:
            lines.append(f'    """{schema.description}"""')
        lines.append("")

        # Default fields if extending
        if schema.use_default_state:
            lines.append("    # Built-in fields")
            lines.append("    messages: Annotated[List[BaseMessage], operator.add]")
            lines.append("    context: Dict[str, Any]")
            lines.append("    current_node: Optional[str]")
            lines.append("    route_decision: str")
            lines.append("")
            lines.append("    # Custom fields")

        for sf in schema.state_fields:
            py_type = _PY_TYPE_STR.get(sf.field_type.value, "Any")
            reducer_code = _REDUCER_CODE.get(sf.reducer.value, "")

            if sf.description and include_comments:
                lines.append(f"    # {sf.description}")

            if reducer_code:
                lines.append(f"    {sf.name}: Annotated[Optional[{py_type}], {reducer_code}]")
            else:
                lines.append(f"    {sf.name}: Optional[{py_type}]")

        lines.append("")
        lines.append("")
        state_class_name = class_name
    else:
        # Use default state
        lines.append("class GraphState(TypedDict, total=False):")
        lines.append('    """Graph state."""')
        lines.append("    messages: Annotated[List[BaseMessage], operator.add]")
        lines.append("    context: Dict[str, Any]")
        lines.append("    current_node: Optional[str]")
        lines.append("    route_decision: str")
        lines.append("")
        lines.append("")
        state_class_name = "GraphState"

    # -- Node functions -----------------------------------------------------
    if include_comments:
        lines.append("# --- Node functions ---")
        lines.append("")

    for node in schema.nodes:
        func_name = _to_func_name(node.label or node.type)
        reads_str = ", ".join(f'"{r}"' for r in node.reads)
        writes_str = ", ".join(f'"{w}"' for w in node.writes)

        lines.append(f"async def {func_name}(state: {state_class_name}) -> Dict[str, Any]:")
        if include_comments:
            lines.append('    """')
            lines.append(f"    Node: {node.label} (type: {node.type})")
            lines.append(f"    Reads: [{reads_str}]")
            lines.append(f"    Writes: [{writes_str}]")
            lines.append('    """')

        # Generate stub implementation based on node type
        if node.type == "agent":
            lines.append("    # TODO: Implement agent logic")
            lines.append(f'    return {{"current_node": "{node.label}", "messages": state.get("messages", [])}}')
        elif node.type == "condition":
            lines.append("    # TODO: Implement condition logic")
            lines.append('    return {"route_decision": "true"}')
        elif node.type == "direct_reply":
            reply = node.config.get("reply_template", "Hello!")
            lines.append(f'    return {{"messages": [AIMessage(content="{reply}")], "current_node": "{node.label}"}}')
        elif node.type == "router_node":
            lines.append("    # TODO: Implement routing logic")
            lines.append('    return {"route_decision": "default"}')
        else:
            lines.append(f"    # TODO: Implement {node.type} logic")
            lines.append(f'    return {{"current_node": "{node.label}"}}')

        lines.append("")
        lines.append("")

    # -- Route functions for conditional nodes ------------------------------
    conditional_nodes = [n for n in schema.nodes if n.type in ("condition", "router_node", "loop_condition_node")]

    for cnode in conditional_nodes:
        func_name = _to_func_name(f"route_{cnode.label or cnode.type}")
        lines.append(f"def {func_name}(state: {state_class_name}) -> str:")
        lines.append(f'    """Route function for {cnode.label}."""')
        lines.append('    return state.get("route_decision", "default")')
        lines.append("")
        lines.append("")

    # -- Build graph --------------------------------------------------------
    if include_comments:
        lines.append("# --- Build graph ---")
        lines.append("")

    lines.append("def build_graph():")
    lines.append(f'    """Build and compile the {schema.name} graph."""')
    lines.append(f"    workflow = StateGraph({state_class_name})")
    lines.append("")

    # Add nodes
    node_func_names: Dict[str, str] = {}
    for node in schema.nodes:
        func_name = _to_func_name(node.label or node.type)
        node_name = node.label or node.type
        node_func_names[node.id] = func_name
        lines.append(f'    workflow.add_node("{node_name}", {func_name})')

    lines.append("")

    # Classify edge sources
    conditional_source_ids = {n.id for n in conditional_nodes}

    # Add conditional edges
    for cnode in conditional_nodes:
        node_name = cnode.label or cnode.type
        route_func = _to_func_name(f"route_{cnode.label or cnode.type}")
        edges_from = [e for e in schema.edges if e.source == cnode.id]

        if edges_from:
            cmap_entries = []
            for e in edges_from:
                target_node = schema.get_node_by_id(e.target)
                target_name = (target_node.label or target_node.type) if target_node else e.target
                rk = e.route_key or "default"
                cmap_entries.append(f'        "{rk}": "{target_name}"')

            lines.append("    workflow.add_conditional_edges(")
            lines.append(f'        "{node_name}",')
            lines.append(f"        {route_func},")
            lines.append("        {")
            lines.append(",\n".join(cmap_entries))
            lines.append("        },")
            lines.append("    )")
            lines.append("")

    # Add normal edges
    for edge in schema.edges:
        if edge.source in conditional_source_ids:
            continue
        source_node = schema.get_node_by_id(edge.source)
        target_node = schema.get_node_by_id(edge.target)
        source_name = (source_node.label or source_node.type) if source_node else edge.source
        target_name = (target_node.label or target_node.type) if target_node else edge.target
        lines.append(f'    workflow.add_edge("{source_name}", "{target_name}")')

    lines.append("")

    # START / END
    start_nodes = schema.get_start_nodes()
    end_nodes = schema.get_end_nodes()

    for sn in start_nodes:
        sn_name = sn.label or sn.type
        lines.append(f'    workflow.add_edge(START, "{sn_name}")')

    for en in end_nodes:
        if en.id not in conditional_source_ids:
            en_name = en.label or en.type
            lines.append(f'    workflow.add_edge("{en_name}", END)')

    lines.append("")
    lines.append("    return workflow.compile()")
    lines.append("")
    lines.append("")

    # -- Main block ---------------------------------------------------------
    if include_main:
        lines.append('if __name__ == "__main__":')
        lines.append("    import asyncio")
        lines.append("")
        lines.append("    async def main():")
        lines.append("        graph = build_graph()")
        lines.append("        result = await graph.ainvoke({")
        lines.append('            "messages": [HumanMessage(content="Hello!")],')
        lines.append('            "context": {},')
        lines.append("        })")
        lines.append('        print("Result:", result)')
        lines.append("")
        lines.append("    asyncio.run(main())")
        lines.append("")

    return "\n".join(lines)


def _to_func_name(label: str) -> str:
    """Convert a node label to a valid Python function name."""
    clean = "".join(c if c.isalnum() or c == "_" else "_" for c in label.lower())
    if not clean or not clean[0].isalpha():
        clean = f"node_{clean}"
    # Collapse multiple underscores
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean.strip("_")
