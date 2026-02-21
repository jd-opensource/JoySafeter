"""
Tests for GraphCompiler and CodeGenerator.
"""

import pytest

from app.core.graph.code_generator import generate_code
from app.core.graph.graph_compiler import CompilationResult, compile_from_schema
from app.core.graph.graph_schema import (
    EdgeSchema,
    EdgeType,
    GraphSchema,
    NodeSchema,
    StateFieldSchema,
    StateFieldType,
)

# ---------------------------------------------------------------------------
# Compiler tests (stub mode — no builder, no LLM resolution needed)
# ---------------------------------------------------------------------------


class TestCompileFromSchema:
    """Test compile_from_schema in stub mode (builder=None)."""

    @pytest.mark.asyncio
    async def test_empty_graph_compiles(self):
        schema = GraphSchema(name="Empty")
        result = await compile_from_schema(schema, validate=False)
        assert isinstance(result, CompilationResult)
        assert result.compiled_graph is not None
        assert result.build_time_ms > 0

    @pytest.mark.asyncio
    async def test_linear_graph_compiles(self):
        schema = GraphSchema(
            name="Linear",
            nodes=[
                NodeSchema(id="a", type="agent", label="A"),
                NodeSchema(id="b", type="direct_reply", label="B"),
            ],
            edges=[EdgeSchema(source="a", target="b")],
        )
        result = await compile_from_schema(schema, validate=False)
        assert result.compiled_graph is not None
        assert len(result.warnings) == 0

    @pytest.mark.asyncio
    async def test_custom_state_fields(self):
        schema = GraphSchema(
            name="CustomState",
            state_fields=[
                StateFieldSchema(name="intent", field_type=StateFieldType.STRING),
            ],
            nodes=[
                NodeSchema(id="a", type="agent", label="A"),
            ],
        )
        result = await compile_from_schema(schema, validate=True)
        assert result.compiled_graph is not None
        assert "intent" in result.state_class.__annotations__

    @pytest.mark.asyncio
    async def test_build_time_tracked(self):
        schema = GraphSchema(
            name="Timed",
            nodes=[NodeSchema(id="a", type="agent", label="A")],
        )
        result = await compile_from_schema(schema)
        assert result.build_time_ms > 0
        assert result.schema.name == "Timed"


# ---------------------------------------------------------------------------
# Code generator tests
# ---------------------------------------------------------------------------


class TestCodeGenerator:
    """Tests for generate_code."""

    def test_basic_code_gen(self):
        schema = GraphSchema(
            name="TestGraph",
            nodes=[
                NodeSchema(id="a", type="agent", label="Agent"),
                NodeSchema(id="b", type="direct_reply", label="Reply"),
            ],
            edges=[EdgeSchema(source="a", target="b")],
        )
        code = generate_code(schema)
        assert "def build_graph():" in code
        assert "StateGraph" in code
        assert "Agent" in code
        assert "Reply" in code
        assert 'if __name__ == "__main__":' in code

    def test_code_gen_without_main(self):
        schema = GraphSchema(name="NoMain")
        code = generate_code(schema, include_main=False)
        assert 'if __name__' not in code

    def test_code_gen_with_state_fields(self):
        schema = GraphSchema(
            name="WithFields",
            state_fields=[
                StateFieldSchema(name="intent", field_type=StateFieldType.STRING, description="User intent"),
                StateFieldSchema(name="score", field_type=StateFieldType.FLOAT),
            ],
            nodes=[NodeSchema(id="a", type="agent", label="A")],
        )
        code = generate_code(schema)
        assert "WithFieldsState" in code
        assert "intent" in code
        assert "score" in code

    def test_code_gen_with_conditional(self):
        schema = GraphSchema(
            name="Conditional",
            nodes=[
                NodeSchema(id="a", type="agent", label="Start"),
                NodeSchema(id="c", type="condition", label="Check"),
                NodeSchema(id="y", type="agent", label="Yes"),
                NodeSchema(id="n", type="agent", label="No"),
            ],
            edges=[
                EdgeSchema(source="a", target="c"),
                EdgeSchema(source="c", target="y", edge_type=EdgeType.CONDITIONAL, route_key="true"),
                EdgeSchema(source="c", target="n", edge_type=EdgeType.CONDITIONAL, route_key="false"),
            ],
        )
        code = generate_code(schema)
        assert "add_conditional_edges" in code
        assert "route_check" in code or "route_" in code

    def test_generated_code_is_valid_python(self):
        """Verify generated code is syntactically valid Python."""
        schema = GraphSchema(
            name="Valid",
            nodes=[
                NodeSchema(id="a", type="agent", label="Agent"),
                NodeSchema(id="b", type="direct_reply", label="Reply"),
            ],
            edges=[EdgeSchema(source="a", target="b")],
        )
        code = generate_code(schema)
        compile(code, "<test>", "exec")  # Raises SyntaxError if invalid
