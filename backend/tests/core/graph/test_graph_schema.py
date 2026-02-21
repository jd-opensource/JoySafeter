"""
Tests for GraphSchema — Pydantic models for declarative graph definitions.
"""

import pytest

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
# StateFieldSchema tests
# ---------------------------------------------------------------------------


class TestStateFieldSchema:
    """Tests for StateFieldSchema Pydantic model."""

    def test_basic_field(self):
        field = StateFieldSchema(name="intent", field_type=StateFieldType.STRING)
        assert field.name == "intent"
        assert field.field_type == StateFieldType.STRING
        assert field.reducer == ReducerType.REPLACE
        assert field.required is False

    def test_field_with_all_options(self):
        field = StateFieldSchema(
            name="confidence",
            field_type=StateFieldType.FLOAT,
            description="Confidence score",
            default=0.0,
            reducer=ReducerType.REPLACE,
            required=True,
        )
        assert field.name == "confidence"
        assert field.field_type == StateFieldType.FLOAT
        assert field.description == "Confidence score"
        assert field.default == 0.0
        assert field.required is True

    def test_invalid_name_rejects(self):
        with pytest.raises(ValueError, match="valid Python identifier"):
            StateFieldSchema(name="123-invalid", field_type=StateFieldType.STRING)

    def test_empty_name_rejects(self):
        with pytest.raises(ValueError):
            StateFieldSchema(name="", field_type=StateFieldType.STRING)

    def test_valid_python_identifier(self):
        # Should not raise
        field = StateFieldSchema(name="my_field_2", field_type=StateFieldType.INT)
        assert field.name == "my_field_2"


# ---------------------------------------------------------------------------
# NodeSchema tests
# ---------------------------------------------------------------------------


class TestNodeSchema:
    """Tests for NodeSchema Pydantic model."""

    def test_basic_node(self):
        node = NodeSchema(id="node-1", type="agent")
        assert node.id == "node-1"
        assert node.type == "agent"
        assert node.reads == ["*"]
        assert node.writes == ["*"]
        assert node.interrupt_before is False

    def test_node_with_reads_writes(self):
        node = NodeSchema(
            id="node-2",
            type="condition",
            label="Check Intent",
            reads=["intent", "messages"],
            writes=["route_decision"],
        )
        assert node.reads == ["intent", "messages"]
        assert node.writes == ["route_decision"]


# ---------------------------------------------------------------------------
# EdgeSchema tests
# ---------------------------------------------------------------------------


class TestEdgeSchema:
    """Tests for EdgeSchema Pydantic model."""

    def test_normal_edge(self):
        edge = EdgeSchema(source="n1", target="n2")
        assert edge.edge_type == EdgeType.NORMAL
        assert edge.route_key is None

    def test_conditional_edge(self):
        edge = EdgeSchema(
            source="n1",
            target="n2",
            edge_type=EdgeType.CONDITIONAL,
            route_key="true",
        )
        assert edge.edge_type == EdgeType.CONDITIONAL
        assert edge.route_key == "true"


# ---------------------------------------------------------------------------
# GraphSchema tests
# ---------------------------------------------------------------------------


class TestGraphSchema:
    """Tests for the top-level GraphSchema model."""

    def _make_linear_schema(self) -> GraphSchema:
        """Helper: A -> B linear graph."""
        return GraphSchema(
            name="Test Graph",
            nodes=[
                NodeSchema(id="a", type="agent", label="Agent A"),
                NodeSchema(id="b", type="direct_reply", label="Reply B"),
            ],
            edges=[
                EdgeSchema(source="a", target="b"),
            ],
        )

    def test_basic_creation(self):
        schema = self._make_linear_schema()
        assert schema.name == "Test Graph"
        assert len(schema.nodes) == 2
        assert len(schema.edges) == 1

    def test_get_node_by_id(self):
        schema = self._make_linear_schema()
        node = schema.get_node_by_id("a")
        assert node is not None
        assert node.label == "Agent A"
        assert schema.get_node_by_id("nonexistent") is None

    def test_get_start_nodes(self):
        schema = self._make_linear_schema()
        starts = schema.get_start_nodes()
        assert len(starts) == 1
        assert starts[0].id == "a"

    def test_get_end_nodes(self):
        schema = self._make_linear_schema()
        ends = schema.get_end_nodes()
        assert len(ends) == 1
        assert ends[0].id == "b"

    def test_get_edges_from(self):
        schema = self._make_linear_schema()
        edges = schema.get_edges_from("a")
        assert len(edges) == 1
        assert edges[0].target == "b"

    def test_get_edges_to(self):
        schema = self._make_linear_schema()
        edges = schema.get_edges_to("b")
        assert len(edges) == 1
        assert edges[0].source == "a"

    def test_edge_references_invalid_source(self):
        with pytest.raises(ValueError, match="unknown source node"):
            GraphSchema(
                nodes=[NodeSchema(id="a", type="agent")],
                edges=[EdgeSchema(source="nonexistent", target="a")],
            )

    def test_edge_references_invalid_target(self):
        with pytest.raises(ValueError, match="unknown target node"):
            GraphSchema(
                nodes=[NodeSchema(id="a", type="agent")],
                edges=[EdgeSchema(source="a", target="nonexistent")],
            )

    def test_duplicate_state_field_names(self):
        with pytest.raises(ValueError, match="Duplicate state field names"):
            GraphSchema(
                state_fields=[
                    StateFieldSchema(name="intent", field_type=StateFieldType.STRING),
                    StateFieldSchema(name="intent", field_type=StateFieldType.INT),
                ],
            )

    def test_serialization_roundtrip(self):
        schema = self._make_linear_schema()
        data = schema.model_dump()
        restored = GraphSchema.model_validate(data)
        assert restored.name == schema.name
        assert len(restored.nodes) == 2
        assert len(restored.edges) == 1

    def test_conditional_graph(self):
        """Test a graph with condition node and conditional edges."""
        schema = GraphSchema(
            name="Conditional",
            nodes=[
                NodeSchema(id="start", type="agent", label="Start"),
                NodeSchema(id="cond", type="condition", label="Check"),
                NodeSchema(id="yes", type="agent", label="Yes Path"),
                NodeSchema(id="no", type="agent", label="No Path"),
            ],
            edges=[
                EdgeSchema(source="start", target="cond"),
                EdgeSchema(source="cond", target="yes", edge_type=EdgeType.CONDITIONAL, route_key="true"),
                EdgeSchema(source="cond", target="no", edge_type=EdgeType.CONDITIONAL, route_key="false"),
            ],
        )
        assert len(schema.get_conditional_node_ids()) == 1
        assert "cond" in schema.get_conditional_node_ids()

    def test_validate_state_dependencies_warns(self):
        schema = GraphSchema(
            state_fields=[
                StateFieldSchema(name="intent", field_type=StateFieldType.STRING),
            ],
            nodes=[
                NodeSchema(
                    id="a",
                    type="agent",
                    label="A",
                    reads=["intent", "nonexistent"],
                    writes=["intent"],
                ),
            ],
        )
        warnings = schema.validate_state_dependencies()
        assert len(warnings) == 1
        assert "nonexistent" in warnings[0]

    def test_validate_state_dependencies_wildcard_ok(self):
        schema = GraphSchema(
            state_fields=[
                StateFieldSchema(name="intent", field_type=StateFieldType.STRING),
            ],
            nodes=[
                NodeSchema(id="a", type="agent", label="A"),  # reads=["*"]
            ],
        )
        warnings = schema.validate_state_dependencies()
        assert len(warnings) == 0


# ---------------------------------------------------------------------------
# build_state_class tests
# ---------------------------------------------------------------------------


class TestBuildStateClass:
    """Tests for the dynamic state class builder."""

    def test_build_with_custom_fields(self):
        from app.core.graph.graph_state import build_state_class

        fields = [
            StateFieldSchema(name="intent", field_type=StateFieldType.STRING),
            StateFieldSchema(name="confidence", field_type=StateFieldType.FLOAT),
        ]
        StateClass = build_state_class(fields)
        assert "intent" in StateClass.__annotations__
        assert "confidence" in StateClass.__annotations__

    def test_build_with_dict_fields(self):
        from app.core.graph.graph_state import build_state_class

        fields = [
            {"name": "score", "field_type": "float", "reducer": "replace"},
        ]
        StateClass = build_state_class(fields, class_name="TestState")
        assert "score" in StateClass.__annotations__

    def test_build_without_extend_default(self):
        from app.core.graph.graph_state import build_state_class

        fields = [
            StateFieldSchema(name="custom_field", field_type=StateFieldType.STRING),
        ]
        StateClass = build_state_class(fields, extend_default=False)
        assert "custom_field" in StateClass.__annotations__
