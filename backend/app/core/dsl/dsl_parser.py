"""DSL Parser — parse Python DSL code into GraphSchema via AST analysis.

The parser performs static analysis only — it never executes user code.
"""

from __future__ import annotations

import ast
import textwrap
from typing import Any

from app.core.dsl.dsl_models import (
    ParsedEdge,
    ParsedNode,
    ParsedStateField,
    ParseError,
    ParseResult,
)
from app.core.graph.graph_schema import (
    EdgeSchema,
    EdgeType,
    GraphSchema,
    NodeSchema,
    ReducerType,
    StateFieldSchema,
    StateFieldType,
)

# ---------------------------------------------------------------------------
# Factory function name → NodeSchema.type mapping
# ---------------------------------------------------------------------------

_FACTORY_TO_NODE_TYPE: dict[str, str] = {
    "agent": "agent",
    "condition": "condition",
    "router": "router_node",
    "fn": "function_node",
    "http": "http_request_node",
    "direct_reply": "direct_reply",
    "human_input": "human_input",
    "tool": "tool_node",
}

# Python type annotation string → StateFieldType
_TYPE_STR_MAP: dict[str, StateFieldType] = {
    "int": StateFieldType.INT,
    "float": StateFieldType.FLOAT,
    "bool": StateFieldType.BOOL,
    "str": StateFieldType.STRING,
    "list": StateFieldType.LIST,
    "dict": StateFieldType.DICT,
}

# Reducer name → ReducerType
_REDUCER_MAP: dict[str, ReducerType] = {
    "add": ReducerType.ADD,
    "append": ReducerType.APPEND,
    "merge": ReducerType.MERGE,
    "add_messages": ReducerType.ADD_MESSAGES,
}


class DSLParser:
    """Parse DSL Python code into intermediate structures or GraphSchema."""

    def parse(self, code: str) -> ParseResult:
        """Parse DSL code → ParseResult (with errors and line numbers).

        Used by the ``/parse`` API endpoint which needs per-line error
        reporting.
        """
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ParseResult(
                errors=[ParseError(line=e.lineno, message=str(e))]
            )

        visitor = _DSLVisitor(source=code)
        visitor.visit(tree)

        # Run validator
        from app.core.dsl.dsl_validator import validate

        validation_errors = validate(visitor.result)
        visitor.result.errors.extend(validation_errors)

        return visitor.result

    def parse_to_schema(
        self, code: str
    ) -> tuple[GraphSchema | None, list[ParseError]]:
        """Parse DSL code → (GraphSchema, errors).

        Used by ``_compile_dsl_graph`` which needs a ``GraphSchema`` directly.
        Returns ``(None, errors)`` if parse fails; ``(schema, [])`` on success.
        """
        result = self.parse(code)
        errors = [e for e in result.errors if e.severity == "error"]
        if errors:
            return None, result.errors
        schema = self._build_schema(result)
        return schema, []

    def _build_schema(self, result: ParseResult) -> GraphSchema:
        """Convert ParseResult → GraphSchema."""
        # Build state fields
        state_fields: list[StateFieldSchema] = []
        for sf in result.state_fields:
            field_type = _TYPE_STR_MAP.get(sf.field_type, StateFieldType.ANY)
            reducer = _REDUCER_MAP.get(sf.reducer, ReducerType.REPLACE) if sf.reducer else ReducerType.REPLACE
            state_fields.append(
                StateFieldSchema(
                    name=sf.name,
                    field_type=field_type,
                    reducer=reducer,
                )
            )

        # Build node schemas — only nodes registered via g.add_node()
        node_schemas: list[NodeSchema] = []
        name_to_parsed: dict[str, ParsedNode] = {}
        for node in result.nodes:
            # node.var_name is the string name from g.add_node("name", var)
            # if the node was registered via add_node; otherwise it's the
            # Python variable name
            name = node.var_name
            name_to_parsed[name] = node

            config = dict(node.kwargs)
            if node.inline_code:
                config["code"] = node.inline_code

            node_schemas.append(
                NodeSchema(
                    id=name,
                    label=name,
                    type=node.node_type,
                    config=config,
                )
            )

        # Build edge schemas — drop START/END edges
        edge_schemas: list[EdgeSchema] = []
        for edge in result.edges:
            if edge.source in ("START", "__start__") or edge.target in ("END", "__end__"):
                continue
            edge_type = EdgeType.CONDITIONAL if edge.route_key is not None else EdgeType.NORMAL
            edge_schemas.append(
                EdgeSchema(
                    source=edge.source,
                    target=edge.target,
                    edge_type=edge_type,
                    route_key=edge.route_key,
                )
            )

        return GraphSchema(
            name="DSL Graph",
            state_fields=state_fields,
            nodes=node_schemas,
            edges=edge_schemas,
        )


# ---------------------------------------------------------------------------
# AST Visitor
# ---------------------------------------------------------------------------


class _DSLVisitor(ast.NodeVisitor):
    """Walk the AST and extract DSL structures."""

    def __init__(self, source: str) -> None:
        self._source = source
        self.result = ParseResult()

        # var_name → ParsedNode (from assignment like `x = agent(...)`)
        self._var_nodes: dict[str, ParsedNode] = {}
        # string name → var_name (from g.add_node("name", var))
        self._name_to_var: dict[str, str] = {}
        # Track the graph variable name
        self._graph_var: str | None = None
        # Track the state class name
        self._state_class_name: str | None = None

    # -- State class ----------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Detect ``class X(GraphState)`` and extract field annotations."""
        is_graph_state = any(
            (isinstance(base, ast.Name) and base.id == "GraphState")
            or (isinstance(base, ast.Attribute) and base.attr == "GraphState")
            for base in node.bases
        )
        if not is_graph_state:
            self.generic_visit(node)
            return

        self._state_class_name = node.name

        for stmt in node.body:
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue

            field_name = stmt.target.id
            field_type, reducer = self._extract_annotation(stmt.annotation)

            self.result.state_fields.append(
                ParsedStateField(
                    name=field_name,
                    field_type=field_type,
                    reducer=reducer,
                )
            )

        self.generic_visit(node)

    def _extract_annotation(self, ann: ast.expr) -> tuple[str, str | None]:
        """Extract type and reducer from an annotation.

        Handles:
        - ``int`` → ("int", None)
        - ``Annotated[list, operator.add]`` → ("list", "add")
        """
        if isinstance(ann, ast.Name):
            return ann.id, None

        if isinstance(ann, ast.Subscript):
            # Check for Annotated[type, reducer]
            if isinstance(ann.value, ast.Name) and ann.value.id == "Annotated":
                slice_node = ann.slice
                if isinstance(slice_node, ast.Tuple) and len(slice_node.elts) >= 2:
                    # First element is the type
                    type_node = slice_node.elts[0]
                    type_str = type_node.id if isinstance(type_node, ast.Name) else "any"

                    # Second element is the reducer
                    reducer_node = slice_node.elts[1]
                    reducer_str = self._extract_reducer_name(reducer_node)
                    return type_str, reducer_str

            # Generic subscript like list[str] — extract base type
            if isinstance(ann.value, ast.Name):
                return ann.value.id, None

        return "any", None

    @staticmethod
    def _extract_reducer_name(node: ast.expr) -> str | None:
        """Extract reducer name from AST node.

        Handles:
        - ``operator.add`` → "add"
        - ``add_messages`` → "add_messages"
        """
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Name):
            return node.id
        return None

    # -- Node assignments -----------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        """Detect node factory calls and JoyGraph instantiation.

        Handles:
        - ``x = agent(...)`` → ParsedNode
        - ``g = JoyGraph(StateClass)`` → graph_var
        """
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            self.generic_visit(node)
            return

        var_name = node.targets[0].id
        value = node.value

        # Check for JoyGraph instantiation: g = JoyGraph(StateClass)
        if isinstance(value, ast.Call):
            func = value.func
            func_name = None
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr

            if func_name == "JoyGraph":
                self._graph_var = var_name
                self.result.graph_var = var_name
                self.generic_visit(node)
                return

            # Check for node factory calls
            if func_name in _FACTORY_TO_NODE_TYPE and func_name != "fn":
                node_type = _FACTORY_TO_NODE_TYPE[func_name]
                kwargs = self._extract_call_kwargs(value)
                parsed = ParsedNode(
                    var_name=var_name,
                    node_type=node_type,
                    kwargs=kwargs,
                )
                self._var_nodes[var_name] = parsed
                self.generic_visit(node)
                return

        self.generic_visit(node)

    # -- @fn decorated functions ----------------------------------------------

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Detect ``@fn(...) async def`` decorated functions."""
        for decorator in node.decorator_list:
            fn_name = None
            fn_kwargs: dict[str, Any] = {}

            if isinstance(decorator, ast.Name) and decorator.id == "fn":
                fn_name = "fn"
            elif isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Name) and func.id == "fn":
                    fn_name = "fn"
                    fn_kwargs = self._extract_call_kwargs(decorator)

            if fn_name:
                # Extract the function body source
                inline_code = self._extract_function_source(node)

                parsed = ParsedNode(
                    var_name=node.name,
                    node_type=_FACTORY_TO_NODE_TYPE["fn"],
                    kwargs=fn_kwargs,
                    inline_code=inline_code,
                )
                self._var_nodes[node.name] = parsed
                return

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Also handle non-async ``@fn`` decorated functions."""
        # Reuse the same logic
        for decorator in node.decorator_list:
            fn_name = None
            fn_kwargs: dict[str, Any] = {}

            if isinstance(decorator, ast.Name) and decorator.id == "fn":
                fn_name = "fn"
            elif isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Name) and func.id == "fn":
                    fn_name = "fn"
                    fn_kwargs = self._extract_call_kwargs(decorator)

            if fn_name:
                inline_code = self._extract_function_source(node)
                parsed = ParsedNode(
                    var_name=node.name,
                    node_type=_FACTORY_TO_NODE_TYPE["fn"],
                    kwargs=fn_kwargs,
                    inline_code=inline_code,
                )
                self._var_nodes[node.name] = parsed
                return

        self.generic_visit(node)

    # -- Expression statements (g.add_node, g.add_edge, etc.) -----------------

    def visit_Expr(self, node: ast.Expr) -> None:
        """Detect graph wiring calls.

        Handles:
        - ``g.add_node("name", var)``
        - ``g.add_edge(src, tgt)``
        - ``g.add_conditional_edges(src, fn, {"key": "target"})``
        """
        if not isinstance(node.value, ast.Call):
            self.generic_visit(node)
            return

        call = node.value
        if not isinstance(call.func, ast.Attribute):
            self.generic_visit(node)
            return

        method_name = call.func.attr
        # Verify it's called on the graph variable
        obj = call.func.value
        if isinstance(obj, ast.Name) and self._graph_var and obj.id != self._graph_var:
            self.generic_visit(node)
            return

        if method_name == "add_node":
            self._handle_add_node(call, node)
        elif method_name == "add_edge":
            self._handle_add_edge(call, node)
        elif method_name == "add_conditional_edges":
            self._handle_add_conditional_edges(call, node)

        self.generic_visit(node)

    def _handle_add_node(self, call: ast.Call, stmt: ast.Expr) -> None:
        """Process ``g.add_node("name", var)``."""
        if len(call.args) < 2:
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_node requires 2 arguments: name and node",
                )
            )
            return

        # First arg: string name
        name_arg = call.args[0]
        if not isinstance(name_arg, ast.Constant) or not isinstance(name_arg.value, str):
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_node first argument must be a string literal",
                )
            )
            return

        string_name = name_arg.value

        # Second arg: variable reference
        var_arg = call.args[1]
        if not isinstance(var_arg, ast.Name):
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_node second argument must be a variable name",
                )
            )
            return

        var_name = var_arg.id

        # Resolve variable to ParsedNode
        parsed = self._var_nodes.get(var_name)
        if parsed is None:
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message=f"add_node references undefined variable '{var_name}'",
                )
            )
            return

        # Register the string name mapping
        self._name_to_var[string_name] = var_name

        # Create a new ParsedNode with the string name as var_name
        # (the string name becomes the node ID in the schema)
        named_node = ParsedNode(
            var_name=string_name,
            node_type=parsed.node_type,
            kwargs=parsed.kwargs,
            inline_code=parsed.inline_code,
        )
        self.result.nodes.append(named_node)

    def _handle_add_edge(self, call: ast.Call, stmt: ast.Expr) -> None:
        """Process ``g.add_edge(src, tgt)``."""
        if len(call.args) < 2:
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_edge requires 2 arguments: source and target",
                )
            )
            return

        source = self._resolve_edge_endpoint(call.args[0])
        target = self._resolve_edge_endpoint(call.args[1])

        if source is None or target is None:
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_edge arguments must be string literals or START/END",
                )
            )
            return

        self.result.edges.append(
            ParsedEdge(source=source, target=target)
        )

    def _handle_add_conditional_edges(self, call: ast.Call, stmt: ast.Expr) -> None:
        """Process ``g.add_conditional_edges(src, fn, {"key": "target"})``."""
        if len(call.args) < 3:
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_conditional_edges requires 3 arguments: source, path_func, path_map",
                )
            )
            return

        source = self._resolve_edge_endpoint(call.args[0])
        if source is None:
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_conditional_edges source must be a string literal or START",
                )
            )
            return

        # Third arg: dict mapping route_key → target
        path_map = call.args[2]
        if not isinstance(path_map, ast.Dict):
            self.result.errors.append(
                ParseError(
                    line=stmt.lineno,
                    message="add_conditional_edges third argument must be a dict literal",
                )
            )
            return

        for key_node, value_node in zip(path_map.keys, path_map.values):
            if key_node is None:
                continue
            route_key = self._extract_constant_str(key_node)
            target = self._resolve_edge_endpoint(value_node)

            if route_key is None or target is None:
                self.result.errors.append(
                    ParseError(
                        line=stmt.lineno,
                        message="conditional edge mapping keys and values must be string literals or END",
                    )
                )
                continue

            self.result.edges.append(
                ParsedEdge(source=source, target=target, route_key=route_key)
            )

    # -- Helpers --------------------------------------------------------------

    def _resolve_edge_endpoint(self, node: ast.expr) -> str | None:
        """Resolve an edge endpoint to a string.

        Handles:
        - ``ast.Constant("node_name")`` → "node_name"
        - ``ast.Name("START")`` → "START"
        - ``ast.Name("END")`` → "END"
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("START", "END"):
                return node.id
            # Could be a variable reference — treat as string name
            return node.id
        return None

    @staticmethod
    def _extract_constant_str(node: ast.expr) -> str | None:
        """Extract a string constant from an AST node."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def _extract_call_kwargs(self, call: ast.Call) -> dict[str, Any]:
        """Extract keyword arguments from a function call as a dict."""
        kwargs: dict[str, Any] = {}
        for kw in call.keywords:
            if kw.arg is None:
                continue
            kwargs[kw.arg] = self._eval_literal(kw.value)

        # Also extract positional args for some factories
        # (not commonly used, but handle gracefully)
        return kwargs

    def _eval_literal(self, node: ast.expr) -> Any:
        """Safely evaluate an AST node as a Python literal.

        Falls back to the source text if the node is not a simple literal.
        """
        try:
            return ast.literal_eval(node)
        except (ValueError, TypeError):
            # For complex expressions, return the source segment
            segment = ast.get_source_segment(self._source, node)
            return segment if segment else "<complex expression>"

    def _extract_function_source(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Extract the full source of a function definition."""
        segment = ast.get_source_segment(self._source, node)
        if segment:
            return segment
        # Fallback: reconstruct from body
        lines = self._source.splitlines()
        start = node.lineno - 1
        end = node.end_lineno if node.end_lineno else start + 1
        return "\n".join(lines[start:end])
