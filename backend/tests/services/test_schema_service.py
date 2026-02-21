"""
Integration tests for SchemaService.

Uses mock DB models (MagicMock objects replicating AgentGraph, GraphNode,
GraphEdge attributes) with AsyncMock repositories.  This verifies the full
service flow — export → validate → code-gen — without a real database.
"""

from __future__ import annotations

# Stub the optional module before any app imports — the import chain
# graph_schema → __init__ → graph_builder_factory → deep_agents_builder →
# pydantic_adapter → pydantic_ai_backends will fail without this.
import sys
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

if "pydantic_ai_backends" not in sys.modules:
    sys.modules["pydantic_ai_backends"] = MagicMock()

from app.core.graph.graph_schema import EdgeType, GraphSchema
from app.services.schema_service import SchemaService

# ---------------------------------------------------------------------------
# Helpers — lightweight mock DB models
# ---------------------------------------------------------------------------


def _make_graph(
    graph_id: uuid.UUID | None = None,
    name: str = "Test Graph",
    description: str | None = None,
) -> MagicMock:
    """Create a mock AgentGraph."""
    g = MagicMock()
    g.id = graph_id or uuid.uuid4()
    g.name = name
    g.description = description
    g.color = None
    g.variables = {}
    g.created_at = None
    g.updated_at = None
    return g


def _make_node(
    node_id: uuid.UUID | None = None,
    node_type: str = "agent",
    label: str = "Agent",
    position_x: float = 0.0,
    position_y: float = 0.0,
    prompt: str = "",
    tools: dict | None = None,
    memory: dict | None = None,
    config: dict | None = None,
) -> MagicMock:
    """Create a mock GraphNode."""
    n = MagicMock()
    n.id = node_id or uuid.uuid4()
    n.type = node_type
    n.position_x = position_x
    n.position_y = position_y
    n.width = 200
    n.height = 100
    n.prompt = prompt
    n.tools = tools or {}
    n.memory = memory or {}
    data = {
        "type": node_type,
        "label": label,
        "config": config or {},
    }
    n.data = data
    return n


def _make_edge(
    source_node_id: uuid.UUID,
    target_node_id: uuid.UUID,
    edge_type: str = "normal",
    route_key: str | None = None,
) -> MagicMock:
    """Create a mock GraphEdge."""
    e = MagicMock()
    e.id = uuid.uuid4()
    e.source_node_id = source_node_id
    e.target_node_id = target_node_id
    e.data = {
        "edge_type": edge_type,
        **({"route_key": route_key} if route_key else {}),
    }
    return e


def _build_mock_service(
    graph: MagicMock | None = None,
    nodes: list | None = None,
    edges: list | None = None,
) -> SchemaService:
    """Build a SchemaService with mocked repos and session."""
    mock_db = AsyncMock()
    svc = SchemaService.__new__(SchemaService)
    svc.db = mock_db

    svc.graph_repo = AsyncMock()
    svc.node_repo = AsyncMock()
    svc.edge_repo = AsyncMock()

    svc.graph_repo.get = AsyncMock(return_value=graph)
    svc.node_repo.list_by_graph = AsyncMock(return_value=nodes or [])
    svc.edge_repo.list_by_graph = AsyncMock(return_value=edges or [])

    return svc


# ---------------------------------------------------------------------------
# Tests — export_schema
# ---------------------------------------------------------------------------


class TestExportSchema:
    """SchemaService.export_schema integration tests."""

    @pytest.mark.asyncio
    async def test_export_linear_graph(self):
        """Export a simple A → B graph."""
        node_a = _make_node(label="Agent A", node_type="agent")
        node_b = _make_node(label="Reply B", node_type="direct_reply")
        edge = _make_edge(node_a.id, node_b.id)
        graph = _make_graph(name="Linear")

        svc = _build_mock_service(graph=graph, nodes=[node_a, node_b], edges=[edge])
        schema = await svc.export_schema(graph.id)

        assert isinstance(schema, GraphSchema)
        assert schema.name == "Linear"
        assert len(schema.nodes) == 2
        assert len(schema.edges) == 1
        assert schema.edges[0].source == str(node_a.id)
        assert schema.edges[0].target == str(node_b.id)

    @pytest.mark.asyncio
    async def test_export_graph_not_found(self):
        """Raises NotFoundException for invalid graph ID."""
        from app.common.exceptions import NotFoundException

        svc = _build_mock_service(graph=None)
        with pytest.raises(NotFoundException):
            await svc.export_schema(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_export_preserves_node_metadata(self):
        """Prompt, tools, memory are captured in node metadata."""
        node = _make_node(
            label="Worker",
            node_type="agent",
            prompt="You are a helpful assistant.",
            tools={"web_search": True},
            memory={"window_size": 5},
        )
        graph = _make_graph()
        svc = _build_mock_service(graph=graph, nodes=[node])

        schema = await svc.export_schema(graph.id)
        exported = schema.nodes[0]
        assert exported.metadata["prompt"] == "You are a helpful assistant."
        assert exported.metadata["tools"] == {"web_search": True}
        assert exported.metadata["memory"] == {"window_size": 5}

    @pytest.mark.asyncio
    async def test_export_conditional_edges(self):
        """Conditional edges preserve route_key and edge_type."""
        cond_node = _make_node(label="Route", node_type="condition")
        yes_node = _make_node(label="Yes", node_type="agent")
        no_node = _make_node(label="No", node_type="agent")
        e_yes = _make_edge(cond_node.id, yes_node.id, "conditional", route_key="true")
        e_no = _make_edge(cond_node.id, no_node.id, "conditional", route_key="false")
        graph = _make_graph(name="Conditional")

        svc = _build_mock_service(
            graph=graph,
            nodes=[cond_node, yes_node, no_node],
            edges=[e_yes, e_no],
        )
        schema = await svc.export_schema(graph.id)

        cond_edges = [e for e in schema.edges if e.edge_type == EdgeType.CONDITIONAL]
        assert len(cond_edges) == 2
        route_keys = {e.route_key for e in cond_edges}
        assert route_keys == {"true", "false"}

    @pytest.mark.asyncio
    async def test_export_empty_graph(self):
        """Graph with no nodes/edges exports successfully."""
        graph = _make_graph(name="Empty")
        svc = _build_mock_service(graph=graph)
        schema = await svc.export_schema(graph.id)

        assert schema.name == "Empty"
        assert len(schema.nodes) == 0
        assert len(schema.edges) == 0

    @pytest.mark.asyncio
    async def test_export_with_custom_state_fields(self):
        """Graph with custom state fields in variables."""
        graph = _make_graph(name="Stateful")
        graph.variables = {
            "state_fields": [
                {"name": "intent", "field_type": "string"},
                {"name": "confidence", "field_type": "float"},
            ]
        }
        svc = _build_mock_service(graph=graph)
        schema = await svc.export_schema(graph.id)

        assert len(schema.state_fields) == 2
        field_names = {f.name for f in schema.state_fields}
        assert field_names == {"intent", "confidence"}


# ---------------------------------------------------------------------------
# Tests — validate_schema
# ---------------------------------------------------------------------------


class TestValidateSchema:
    """SchemaService.validate_schema integration tests."""

    @pytest.mark.asyncio
    async def test_valid_linear_graph(self):
        """A well-formed graph validates without errors."""
        node_a = _make_node(label="A", node_type="agent")
        node_b = _make_node(label="B", node_type="direct_reply")
        edge = _make_edge(node_a.id, node_b.id)
        graph = _make_graph()

        svc = _build_mock_service(graph=graph, nodes=[node_a, node_b], edges=[edge])
        result = await svc.validate_schema(graph.id)

        assert result["valid"] is True
        assert len(result["errors"]) == 0
        assert result["node_count"] == 2
        assert result["edge_count"] == 1

    @pytest.mark.asyncio
    async def test_graph_not_found_returns_invalid(self):
        """Non-existent graph returns valid=False with error."""
        svc = _build_mock_service(graph=None)
        result = await svc.validate_schema(uuid.uuid4())

        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    @pytest.mark.asyncio
    async def test_empty_graph_warns(self):
        """Empty graph generates a "no nodes" warning."""
        graph = _make_graph()
        svc = _build_mock_service(graph=graph)
        result = await svc.validate_schema(graph.id)

        assert any("no nodes" in w for w in result["warnings"])


# ---------------------------------------------------------------------------
# Tests — export_code
# ---------------------------------------------------------------------------


class TestExportCode:
    """SchemaService.export_code integration tests."""

    @pytest.mark.asyncio
    async def test_export_code_generates_valid_python(self):
        """Exported code is syntactically valid Python."""
        node_a = _make_node(label="Agent", node_type="agent")
        node_b = _make_node(label="Reply", node_type="direct_reply")
        edge = _make_edge(node_a.id, node_b.id)
        graph = _make_graph(name="MyGraph")

        svc = _build_mock_service(graph=graph, nodes=[node_a, node_b], edges=[edge])
        code = await svc.export_code(graph.id)

        # Must be valid Python
        compile(code, "<test>", "exec")
        assert "def build_graph():" in code
        assert "StateGraph" in code

    @pytest.mark.asyncio
    async def test_export_code_includes_main(self):
        """Default export includes __main__ block."""
        node = _make_node(label="A", node_type="agent")
        graph = _make_graph()
        svc = _build_mock_service(graph=graph, nodes=[node])

        code = await svc.export_code(graph.id, include_main=True)
        assert '__name__' in code

    @pytest.mark.asyncio
    async def test_export_code_without_main(self):
        """Export without __main__ block when include_main=False."""
        node = _make_node(label="A", node_type="agent")
        graph = _make_graph()
        svc = _build_mock_service(graph=graph, nodes=[node])

        code = await svc.export_code(graph.id, include_main=False)
        assert '__main__' not in code


# ---------------------------------------------------------------------------
# Tests — import_schema
# ---------------------------------------------------------------------------


class TestImportSchema:
    """SchemaService.import_schema integration tests."""

    @pytest.mark.asyncio
    async def test_import_creates_graph_and_nodes(self):
        """Import creates a new graph + nodes + edges in DB."""
        node_a_id = str(uuid.uuid4())
        node_b_id = str(uuid.uuid4())
        schema_data = {
            "name": "Imported",
            "description": "A test import",
            "nodes": [
                {"id": node_a_id, "type": "agent", "label": "A"},
                {"id": node_b_id, "type": "direct_reply", "label": "B"},
            ],
            "edges": [
                {"source": node_a_id, "target": node_b_id},
            ],
        }

        mock_db = AsyncMock()
        svc = SchemaService.__new__(SchemaService)
        svc.db = mock_db

        created_graph = MagicMock()
        created_graph.id = uuid.uuid4()

        svc.graph_repo = AsyncMock()
        svc.graph_repo.create = AsyncMock(return_value=created_graph)
        svc.node_repo = AsyncMock()
        svc.node_repo.create = AsyncMock()
        svc.edge_repo = AsyncMock()
        svc.edge_repo.create = AsyncMock()

        user_id = uuid.uuid4()
        result_id = await svc.import_schema(schema_data, user_id=user_id)

        assert result_id == created_graph.id
        # Should have created 1 graph, 2 nodes, 1 edge
        svc.graph_repo.create.assert_called_once()
        assert svc.node_repo.create.call_count == 2
        assert svc.edge_repo.create.call_count == 1

    @pytest.mark.asyncio
    async def test_import_invalid_schema_raises(self):
        """Invalid schema data raises ValidationError."""
        svc = _build_mock_service()
        # nodes with missing required 'type' field triggers Pydantic ValidationError
        with pytest.raises(Exception):
            await svc.import_schema(
                {"name": "Bad", "nodes": [{"id": "n1"}]},  # missing 'type'
                user_id=uuid.uuid4(),
            )


# ---------------------------------------------------------------------------
# Tests — roundtrip (export → validate → code)
# ---------------------------------------------------------------------------


class TestSchemaRoundtrip:
    """End-to-end roundtrip through the service layer."""

    @pytest.mark.asyncio
    async def test_export_then_validate(self):
        """Export a schema, then validate it — should be consistent."""
        node_a = _make_node(label="Agent", node_type="agent")
        node_b = _make_node(label="Reply", node_type="direct_reply")
        edge = _make_edge(node_a.id, node_b.id)
        graph = _make_graph(name="Roundtrip")

        svc = _build_mock_service(graph=graph, nodes=[node_a, node_b], edges=[edge])

        schema = await svc.export_schema(graph.id)
        assert schema is not None

        result = await svc.validate_schema(graph.id)
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_export_then_code_gen(self):
        """Export → code generation pipeline."""
        node_a = _make_node(label="Agent A", node_type="agent")
        node_b = _make_node(label="Reply B", node_type="direct_reply")
        edge = _make_edge(node_a.id, node_b.id)
        graph = _make_graph(name="Pipeline")

        svc = _build_mock_service(graph=graph, nodes=[node_a, node_b], edges=[edge])
        code = await svc.export_code(graph.id)

        # Verify the generated code references the graph nodes
        assert "Agent_A" in code or "Agent" in code
        assert "StateGraph" in code
        compile(code, "<test>", "exec")

    @pytest.mark.asyncio
    async def test_schema_serialization_roundtrip(self):
        """Export → serialize → deserialize → compare."""
        node_a = _make_node(label="Worker", node_type="agent")
        node_b = _make_node(label="Output", node_type="direct_reply")
        edge = _make_edge(node_a.id, node_b.id)
        graph = _make_graph(name="Serialize")

        svc = _build_mock_service(graph=graph, nodes=[node_a, node_b], edges=[edge])
        schema = await svc.export_schema(graph.id)

        # Serialize and deserialize
        data = schema.model_dump()
        restored = GraphSchema.model_validate(data)

        assert restored.name == schema.name
        assert len(restored.nodes) == len(schema.nodes)
        assert len(restored.edges) == len(schema.edges)
        assert restored.nodes[0].type == schema.nodes[0].type

    @pytest.mark.asyncio
    async def test_conditional_graph_full_pipeline(self):
        """Conditional graph: export → validate → code gen."""
        start = _make_node(label="Start", node_type="agent")
        cond = _make_node(label="Check", node_type="condition")
        yes_node = _make_node(label="Yes", node_type="agent")
        no_node = _make_node(label="No", node_type="direct_reply")

        e1 = _make_edge(start.id, cond.id)
        e_yes = _make_edge(cond.id, yes_node.id, "conditional", route_key="true")
        e_no = _make_edge(cond.id, no_node.id, "conditional", route_key="false")

        graph = _make_graph(name="ConditionalPipeline")
        svc = _build_mock_service(
            graph=graph,
            nodes=[start, cond, yes_node, no_node],
            edges=[e1, e_yes, e_no],
        )

        # Export
        schema = await svc.export_schema(graph.id)
        assert len(schema.nodes) == 4
        assert len(schema.edges) == 3

        # Validate
        result = await svc.validate_schema(graph.id)
        assert result["valid"] is True

        # Code gen
        code = await svc.export_code(graph.id)
        assert "add_conditional_edges" in code
        compile(code, "<test>", "exec")
