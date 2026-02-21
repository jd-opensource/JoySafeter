
import pytest
from langgraph.types import Command
from pydantic import ValidationError

from app.core.graph.graph_schema import GraphSchema, NodeSchema, EdgeSchema, StateFieldSchema
from app.core.graph.graph_compiler import compile_from_schema
from app.core.graph.graph_state import GraphState

@pytest.mark.asyncio
async def test_global_error_policy():
    """Test that an unhandled exception triggers a jump to the fallback node."""
    
    # Define a node that raises an error
    error_node = NodeSchema(
        id="node_error",
        type="function_node",
        label="Error Node",
    )
    
    # Define a fallback node
    fallback_node = NodeSchema(
        id="node_fallback",
        type="function_node",
        label="Fallback Node",
    )

    # Define state fields
    state_fields = [
        StateFieldSchema(name="result", field_type="any", reducer="replace"),
        StateFieldSchema(name="error", field_type="string", reducer="replace"),
        StateFieldSchema(name="error_source_node", field_type="string", reducer="replace"),
        StateFieldSchema(name="error_timestamp", field_type="float", reducer="replace"),
    ]

    schema = GraphSchema(
        name="Error Policy Test",
        nodes=[error_node, fallback_node],
        edges=[
            EdgeSchema(source="node_error", target="node_fallback"), 
        ],
        fallback_node_id="node_fallback",
        state_fields=state_fields,
        use_default_state=False, 
    )
    
    # Mock builder to create executors
    class MockNode:
        def __init__(self, node_id):
            self.id = node_id

    class MockBuilder:
        def __init__(self):
            # Populate builder.nodes with mocks matching schema IDs
            self.nodes = [
                MockNode("node_error"),
                MockNode("node_fallback")
            ]
            self._node_id_to_name = {}

        async def _get_or_create_executor(self, db_node, name):
            # Return simple async callables
            if db_node.id == "node_error":
                async def error_exec(state: GraphState):
                    raise ValueError("Intentional Failure")
                return error_exec
            else:
                async def fallback_exec(state: GraphState):
                    # Fallback node logic
                    return {"result": "Recovered"}
                return fallback_exec

        async def _create_node_executor(self, *args):
            pass

    # Compile
    result = await compile_from_schema(schema, builder=MockBuilder(), checkpointer=False)
    compiled = result.compiled_graph
    
    # Run
    # Current LangGraph behavior: Command(goto=...) interrupts the current node and schedules the target.
    # We need to ensure we can run it.
    
    inputs = GraphState()
    
    # Use a try-except block just in case, but expectation is graceful handling
    try:
        # Run until end. The 'node_error' should be the start node implicitly or explicit start
        # If no start node defined, we need to be careful.
        # graph_compiler auto-adds start edge to nodes with no incoming.
        # Here 'node_error' has no incoming, so it's a start node.
        
        final_state = await compiled.ainvoke(inputs)
        
        print(f"DEBUG: final_state type: {type(final_state)}")
        print(f"DEBUG: final_state content: {final_state}")

        # Check if fallback was executed
        # The fallback node returns {"result": "Recovered"}
        # And the wrapper adds "error" info to state before jumping
        
        if final_state is None:
             pytest.fail("final_state is None! Check graph execution.")

        assert final_state.get("result") == "Recovered"
        assert final_state.get("error") == "Intentional Failure"
        assert final_state.get("error_source_node") == "node_error"
        
    except Exception as e:
        pytest.fail(f"Graph raised exception instead of fallback: {e}")

@pytest.mark.asyncio
async def test_global_error_validation():
    """Test schema validation for fallback_node_id."""
    
    with pytest.raises(ValidationError, match="Fallback node ID 'missing_node' not found"):
        GraphSchema(
            nodes=[NodeSchema(id="n1", type="test")],
            fallback_node_id="missing_node"
        )
