"""DSL Validator — post-parse semantic checks on ParseResult."""

from __future__ import annotations

import ast

from app.core.dsl.dsl_models import ParseError, ParseResult


def validate(result: ParseResult) -> list[ParseError]:
    """Run semantic validation on a ParseResult.

    Returns a list of errors/warnings to append to ``result.errors``.
    """
    errors: list[ParseError] = []

    # Collect all registered node string names
    node_names: set[str] = set()
    duplicate_names: set[str] = set()
    for node in result.nodes:
        if node.var_name in node_names:
            duplicate_names.add(node.var_name)
        node_names.add(node.var_name)

    # 1. Duplicate node string names
    for name in duplicate_names:
        errors.append(
            ParseError(
                line=None,
                message=f"Duplicate node name '{name}' — each node must have a unique name",
            )
        )

    # 2. All nodes referenced in edges are defined (skip START/END)
    for edge in result.edges:
        if edge.source not in ("START", "END") and edge.source not in node_names:
            errors.append(
                ParseError(
                    line=None,
                    message=f"Edge references undefined node '{edge.source}'",
                )
            )
        if edge.target not in ("START", "END") and edge.target not in node_names:
            errors.append(
                ParseError(
                    line=None,
                    message=f"Edge references undefined node '{edge.target}'",
                )
            )

    # 3. Entry point exists (at least one node with no incoming non-START edges)
    if result.nodes:
        targets = {
            e.target
            for e in result.edges
            if e.source not in ("START",)
        }
        start_targets = {e.target for e in result.edges if e.source == "START"}
        nodes_with_no_incoming = {
            n.var_name for n in result.nodes if n.var_name not in targets
        }
        has_entry = bool(nodes_with_no_incoming) or bool(start_targets)
        if not has_entry:
            errors.append(
                ParseError(
                    line=None,
                    message="No entry point found — at least one node must have no incoming edges or be connected from START",
                )
            )

    # 4. Conditional edge route keys match node type expectations
    # condition nodes should have "true"/"false" route keys
    condition_nodes = {n.var_name for n in result.nodes if n.node_type == "condition"}
    conditional_edges_by_source: dict[str, list[str]] = {}
    for edge in result.edges:
        if edge.route_key is not None:
            conditional_edges_by_source.setdefault(edge.source, []).append(edge.route_key)

    for source, keys in conditional_edges_by_source.items():
        if source in condition_nodes:
            invalid_keys = set(keys) - {"true", "false"}
            if invalid_keys:
                errors.append(
                    ParseError(
                        line=None,
                        message=f"Condition node '{source}' has invalid route keys {invalid_keys} — expected 'true'/'false'",
                    )
                )

    # 5. Orphaned nodes (defined but never connected)
    connected_nodes: set[str] = set()
    for edge in result.edges:
        if edge.source not in ("START", "END"):
            connected_nodes.add(edge.source)
        if edge.target not in ("START", "END"):
            connected_nodes.add(edge.target)

    for node in result.nodes:
        if node.var_name not in connected_nodes:
            errors.append(
                ParseError(
                    line=None,
                    message=f"Node '{node.var_name}' is defined but never connected in the graph",
                    severity="warning",
                )
            )

    # 6. @fn inline code is syntactically valid Python
    for node in result.nodes:
        if node.inline_code:
            try:
                ast.parse(node.inline_code)
            except SyntaxError as e:
                errors.append(
                    ParseError(
                        line=e.lineno,
                        message=f"Syntax error in @fn node '{node.var_name}': {e.msg}",
                    )
                )

    return errors
