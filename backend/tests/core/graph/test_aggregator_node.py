import pytest
from unittest.mock import MagicMock
from app.core.graph.node_executors import AggregatorNodeExecutor
from app.core.graph.graph_state import GraphState

@pytest.fixture
def mock_node():
    node = MagicMock()
    node.data = {"config": {}}
    return node

@pytest.mark.asyncio
async def test_aggregator_append(mock_node):
    # Config: Append 'scores' to 'all_scores'
    mock_node.data["config"] = {
        "method": "append",
        "source_variables": ["scores"],
        "target_variable": "all_scores"
    }
    executor = AggregatorNodeExecutor(mock_node, "aggregator_1")
    
    # State has a list of scores from parallel branches
    state = GraphState(scores=[10, 20, 30])
    
    result = await executor(state)
    
    assert result["all_scores"] == [10, 20, 30]
    assert result["status"] == "success"

@pytest.mark.asyncio
async def test_aggregator_sum(mock_node):
    # Config: Sum 'scores' into 'total_score'
    mock_node.data["config"] = {
        "method": "sum",
        "source_variables": ["scores"],
        "target_variable": "total_score"
    }
    executor = AggregatorNodeExecutor(mock_node, "aggregator_2")
    
    state = GraphState(scores=[10, 20, 30])
    
    result = await executor(state)
    
    assert result["total_score"] == 60

@pytest.mark.asyncio
async def test_aggregator_merge(mock_node):
    # Config: Merge 'partial_results' dicts into 'final_result'
    mock_node.data["config"] = {
        "method": "merge",
        "source_variables": ["partial_results"],
        "target_variable": "final_result"
    }
    executor = AggregatorNodeExecutor(mock_node, "aggregator_3")
    
    # Simulating that state has collected a list of dicts (e.g. from parallel nodes writing to same list var)
    state = GraphState(partial_results=[{"a": 1}, {"b": 2}])
    
    result = await executor(state)
    
    assert result["final_result"] == {"a": 1, "b": 2}

@pytest.mark.asyncio
async def test_aggregator_latest(mock_node):
    # Config: Get latest 'status_update'
    mock_node.data["config"] = {
        "method": "latest",
        "source_variables": ["updates"],
        "target_variable": "latest_update"
    }
    executor = AggregatorNodeExecutor(mock_node, "aggregator_4")
    
    state = GraphState(updates=["step1", "step2", "step3"])
    
    result = await executor(state)
    
    assert result["latest_update"] == "step3"

@pytest.mark.asyncio
async def test_aggregator_multiple_sources(mock_node):
    # Config: Append from multiple vars
    mock_node.data["config"] = {
        "method": "append",
        "source_variables": ["var_a", "var_b"],
        "target_variable": "combined"
    }
    executor = AggregatorNodeExecutor(mock_node, "aggregator_5")
    
    state = GraphState(var_a=[1, 2], var_b=[3, 4])
    
    result = await executor(state)
    
    # Order depends on iteration order of source_variables
    # var_a then var_b -> [1, 2, 3, 4]
    assert result["combined"] == [1, 2, 3, 4]
