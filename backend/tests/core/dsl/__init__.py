"""Tests for DSL models, validator, and SDK — no heavy dependencies."""

import ast
import pytest

from app.core.dsl.dsl_models import (
    ParsedEdge,
    ParsedNode,
    ParsedStateField,
    ParseError,
    ParseResult,
)
from app.core.dsl.dsl_validator import validate
from app.joysafeter.nodes import (
    NodeDef,
    agent,
    condition,
    direct_reply,
    fn,
    http,
    human_input,
    router,
    tool,
)


# ---------------------------------------------------------------------------
# dsl_models
# ---------------------------------------------------------------------------


class TestParseResult:
    def test_empty_result(self):
        r = ParseResult()
        assert r.state_fields == []
        assert r.nodes == []
        assert r.edges == []
        assert r.graph_var is None
        assert r.errors == []

    def test_state_field(self):
        sf = ParsedStateField(name="score", field_type="int", reducer=None)
        assert sf.name == "score"
        assert sf.field_type == "int"
        assert sf.reducer is None

    def test_state_field_with_reducer(self):
        sf = ParsedStateField(name="messages", field_type="list", reducer="add")
        assert sf.reducer == "add"

    def test_parsed_node(self):
        n = ParsedNode(var_name="cls", node_type="agent", kwargs={"model": "x"})
        assert n.var_name == "cls"
        assert n.node_type == "agent"
        assert n.kwargs == {"model": "x"}
        assert n.inline_code is None

    def test_parsed_node_with_code(self):
        n = ParsedNode(
            var_name="scorer",
            node_type="function_node",
            kwargs={"writes": ["score"]},
            inline_code="async def scorer(state):\n    return {'score': 1}",
        )
        assert n.inline_code is not None

    def test_parsed_edge(self):
        e = ParsedEdge(source="a", target="b")
        assert e.route_key is None

    def test_parsed_edge_conditional(self):
        e = ParsedEdge(source="gate", target="yes", route_key="true")
        assert e.route_key == "true"

    def test_parse_error(self):
        e = ParseError(line=5, message="bad syntax")
        assert e.severity == "error"

    def test_parse_error_warning(self):
        e = ParseError(line=None, message="orphan", severity="warning")
        assert e.severity == "warning"


# ---------------------------------------------------------------------------
# joysafeter SDK
# ---------------------------------------------------------------------------


class TestSDKFactories:
    def test_agent(self):
        n = agent(model="deepseek", system_prompt="hello")
        assert isinstance(n, NodeDef)
        assert n.node_type == "agent"
        assert n.kwargs == {"model": "deepseek", "system_prompt": "hello"}

    def test_condition(self):
        n = condition(expression="state.get('x') > 5")
        assert n.node_type == "condition"
        assert n.kwargs["expression"] == "state.get('x') > 5"

    def test_router(self):
        n = router(routes=[("a", "b")], default="c")
        assert n.node_type == "router_node"

    def test_http(self):
        n = http(method="GET", url="https://example.com")
        assert n.node_type == "http_request_node"

    def test_direct_reply(self):
        n = direct_reply(template="Hello {{name}}")
        assert n.node_type == "direct_reply"

    def test_human_input(self):
        n = human_input()
        assert n.node_type == "human_input"
        assert n.kwargs == {}

    def test_tool(self):
        n = tool(tool_name="search")
        assert n.node_type == "tool_node"

    def test_fn_decorator(self):
        @fn(writes=["score"])
        async def scorer(state):
            return {"score": 1}

        assert hasattr(scorer, "_fn_kwargs")
        assert scorer._fn_kwargs == {"writes": ["score"]}

    def test_fn_decorator_no_args(self):
        @fn()
        async def noop(state):
            pass

        assert hasattr(noop, "_fn_kwargs")
        assert noop._fn_kwargs == {}


# ---------------------------------------------------------------------------
# dsl_validator
# ---------------------------------------------------------------------------


class TestValidator:
    def _make_result(self, nodes=None, edges=None):
        return ParseResult(
            nodes=nodes or [],
            edges=edges or [],
        )

    def test_valid_graph(self):
        r = self._make_result(
            nodes=[
                ParsedNode(var_name="a", node_type="agent", kwargs={}),
                ParsedNode(var_name="b", node_type="direct_reply", kwargs={}),
            ],
            edges=[
                ParsedEdge(source="START", target="a"),
                ParsedEdge(source="a", target="b"),
                ParsedEdge(source="b", target="END"),
            ],
        )
        errors = validate(r)
        real_errors = [e for e in errors if e.severity == "error"]
        assert len(real_errors) == 0

    def test_undefined_node_in_edge(self):
        r = self._make_result(
            nodes=[ParsedNode(var_name="a", node_type="agent", kwargs={})],
            edges=[ParsedEdge(source="a", target="missing")],
        )
        errors = validate(r)
        msgs = [e.message for e in errors if e.severity == "error"]
        assert any("undefined node" in m.lower() for m in msgs)

    def test_duplicate_node_name(self):
        r = self._make_result(
            nodes=[
                ParsedNode(var_name="a", node_type="agent", kwargs={}),
                ParsedNode(var_name="a", node_type="condition", kwargs={}),
            ],
            edges=[ParsedEdge(source="START", target="a")],
        )
        errors = validate(r)
        msgs = [e.message for e in errors if e.severity == "error"]
        assert any("duplicate" in m.lower() for m in msgs)

    def test_orphaned_node_warning(self):
        r = self._make_result(
            nodes=[
                ParsedNode(var_name="a", node_type="agent", kwargs={}),
                ParsedNode(var_name="orphan", node_type="agent", kwargs={}),
            ],
            edges=[
                ParsedEdge(source="START", target="a"),
                ParsedEdge(source="a", target="END"),
            ],
        )
        errors = validate(r)
        warnings = [e for e in errors if e.severity == "warning"]
        assert any("orphan" in e.message.lower() for e in warnings)

    def test_invalid_condition_route_key(self):
        r = self._make_result(
            nodes=[
                ParsedNode(var_name="gate", node_type="condition", kwargs={}),
                ParsedNode(var_name="a", node_type="agent", kwargs={}),
            ],
            edges=[
                ParsedEdge(source="START", target="gate"),
                ParsedEdge(source="gate", target="a", route_key="maybe"),
            ],
        )
        errors = validate(r)
        msgs = [e.message for e in errors if e.severity == "error"]
        assert any("invalid route key" in m.lower() for m in msgs)

    def test_valid_condition_route_keys(self):
        r = self._make_result(
            nodes=[
                ParsedNode(var_name="gate", node_type="condition", kwargs={}),
                ParsedNode(var_name="a", node_type="agent", kwargs={}),
                ParsedNode(var_name="b", node_type="agent", kwargs={}),
            ],
            edges=[
                ParsedEdge(source="START", target="gate"),
                ParsedEdge(source="gate", target="a", route_key="true"),
                ParsedEdge(source="gate", target="b", route_key="false"),
            ],
        )
        errors = validate(r)
        real_errors = [e for e in errors if e.severity == "error"]
        assert len(real_errors) == 0

    def test_invalid_fn_code(self):
        r = self._make_result(
            nodes=[
                ParsedNode(
                    var_name="bad",
                    node_type="function_node",
                    kwargs={},
                    inline_code="def bad(:\n  pass",  # syntax error
                ),
            ],
            edges=[ParsedEdge(source="START", target="bad")],
        )
        errors = validate(r)
        msgs = [e.message for e in errors if e.severity == "error"]
        assert any("syntax error" in m.lower() for m in msgs)

    def test_start_end_edges_not_flagged(self):
        """START/END should not be flagged as undefined nodes."""
        r = self._make_result(
            nodes=[ParsedNode(var_name="a", node_type="agent", kwargs={})],
            edges=[
                ParsedEdge(source="START", target="a"),
                ParsedEdge(source="a", target="END"),
            ],
        )
        errors = validate(r)
        real_errors = [e for e in errors if e.severity == "error"]
        assert len(real_errors) == 0
