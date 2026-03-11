"""Tests that lock the Runtime State & Context Contract.

These tests intentionally focus on:
- GraphSchema.from_db reading graph.variables.state_fields
- Dynamic state class creation via build_state_class

They do NOT depend on a running DB. Instead they use lightweight stubs
that match the minimal shape GraphSchema.from_db expects.

Contract doc: docs/runtime_state_context_contract.md
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.graph.graph_schema import GraphSchema
from app.core.graph.graph_state import build_state_class


@dataclass
class _StubGraph:
    """Minimal graph object compatible with GraphSchema.from_db."""

    name: str = "Stub Graph"
    description: str | None = None
    variables: dict | None = None


def test_graphschema_from_db_reads_state_fields_from_graph_variables():
    graph = _StubGraph(
        variables={
            "state_fields": [
                {"name": "intent", "field_type": "string", "reducer": "replace"},
                {"name": "score", "field_type": "float", "reducer": "replace"},
            ]
        }
    )

    # nodes/edges are irrelevant for state_fields parsing
    schema = GraphSchema.from_db(graph=graph, nodes=[], edges=[])

    assert len(schema.state_fields) == 2
    assert {f.name for f in schema.state_fields} == {"intent", "score"}


def test_build_state_class_extends_default_state_by_default():
    # Contract expectation: custom fields should be available alongside default GraphState
    StateClass = build_state_class(
        [
            {"name": "intent", "field_type": "string", "reducer": "replace"},
        ],
        extend_default=True,
    )

    # Custom field exists
    assert "intent" in StateClass.__annotations__

    # Default fields from GraphState exist (at minimum context/messages)
    assert "context" in StateClass.__annotations__
    assert "messages" in StateClass.__annotations__


@pytest.mark.parametrize("extend_default", [True, False])
def test_build_state_class_extend_default_flag_controls_presence_of_default_fields(extend_default: bool):
    StateClass = build_state_class(
        [
            {"name": "custom_field", "field_type": "string", "reducer": "replace"},
        ],
        extend_default=extend_default,
    )

    assert "custom_field" in StateClass.__annotations__

    if extend_default:
        assert "context" in StateClass.__annotations__
        assert "messages" in StateClass.__annotations__
    else:
        # When not extending default state, default GraphState fields must not be assumed.
        assert "context" not in StateClass.__annotations__
        assert "messages" not in StateClass.__annotations__
