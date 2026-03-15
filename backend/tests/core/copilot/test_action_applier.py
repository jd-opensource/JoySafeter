"""
Contract tests for apply_actions_to_graph_state.

Uses shared fixtures from docs/schemas/copilot-apply-fixtures.json to ensure
backend apply logic stays consistent with the contract (and with frontend ActionProcessor).
"""

import importlib.util
import json
from pathlib import Path

import pytest

# Import only action_applier to avoid pulling in langchain/copilot agent dependencies
_action_applier_path = (
    Path(__file__).resolve().parent.parent.parent.parent / "app" / "core" / "copilot" / "action_applier.py"
)
_spec = importlib.util.spec_from_file_location("action_applier", _action_applier_path)
_action_applier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_action_applier)
apply_actions_to_graph_state = _action_applier.apply_actions_to_graph_state

FIXTURES_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent / "docs" / "schemas" / "copilot-apply-fixtures.json"
)


def _load_fixtures():
    if not FIXTURES_PATH.exists():
        return []
    with open(FIXTURES_PATH, encoding="utf-8") as f:
        return json.load(f)


APPLY_FIXTURES = _load_fixtures()


def _normalize_nodes(nodes):
    """Sort nodes by id for stable comparison."""
    return sorted(nodes, key=lambda n: n.get("id", ""))


def _normalize_edges(edges):
    """Sort edges by id for stable comparison."""
    return sorted(edges, key=lambda e: e.get("id", ""))


def _node_contract_match(got_node, want_node):
    """Check that got_node matches contract: id, type, position, data.label, data.type, and config superset."""
    if got_node.get("id") != want_node.get("id"):
        return False
    if got_node.get("type") != want_node.get("type"):
        return False
    if got_node.get("position") != want_node.get("position"):
        return False
    got_data = got_node.get("data") or {}
    want_data = want_node.get("data") or {}
    if got_data.get("label") != want_data.get("label"):
        return False
    if got_data.get("type") != want_data.get("type"):
        return False
    want_config = want_data.get("config") or {}
    got_config = got_data.get("config") or {}
    for k, v in want_config.items():
        if got_config.get(k) != v:
            return False
    return True


def _edge_contract_match(got_edge, want_edge):
    """Check that got_edge matches contract: id, source, target."""
    return (
        got_edge.get("id") == want_edge.get("id")
        and got_edge.get("source") == want_edge.get("source")
        and got_edge.get("target") == want_edge.get("target")
    )


@pytest.mark.parametrize(
    "case_index",
    range(len(APPLY_FIXTURES)) if APPLY_FIXTURES else [0],
    ids=[APPLY_FIXTURES[i]["name"] for i in range(len(APPLY_FIXTURES))] if APPLY_FIXTURES else ["no_fixtures"],
)
def test_apply_actions_contract(case_index):
    """Each fixture case: apply actions and assert result matches expected (contract match)."""
    if not APPLY_FIXTURES:
        pytest.skip(f"Fixtures not found: {FIXTURES_PATH}")
    data = APPLY_FIXTURES[case_index]
    name = data.get("name", f"case_{case_index}")
    initial_nodes = data["initial_nodes"]
    initial_edges = data["initial_edges"]
    actions = data["actions"]
    expected_nodes = data["expected_nodes"]
    expected_edges = data["expected_edges"]

    got_nodes, got_edges = apply_actions_to_graph_state(
        [n.copy() for n in initial_nodes],
        [e.copy() for e in initial_edges],
        actions,
    )
    got_nodes = _normalize_nodes(got_nodes)
    got_edges = _normalize_edges(got_edges)
    exp_nodes = _normalize_nodes(expected_nodes)
    exp_edges = _normalize_edges(expected_edges)

    assert len(got_nodes) == len(exp_nodes), f"{name}: node count mismatch"
    assert len(got_edges) == len(exp_edges), f"{name}: edge count mismatch"
    for i, (g, e) in enumerate(zip(got_nodes, exp_nodes)):
        assert _node_contract_match(g, e), f"{name}: node[{i}] contract mismatch: got {g}"
    for i, (g, e) in enumerate(zip(got_edges, exp_edges)):
        assert _edge_contract_match(g, e), f"{name}: edge[{i}] contract mismatch: got {g}"
