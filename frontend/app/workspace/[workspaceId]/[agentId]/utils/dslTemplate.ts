/**
 * Starter template for new DSL graphs.
 * Valid DSL that parses cleanly and produces a runnable single-node graph.
 */
export const DSL_STARTER_TEMPLATE = `from joysafeter.nodes import agent, direct_reply
from joysafeter import JoyGraph, GraphState
from langgraph.graph import START, END
from typing import Annotated
import operator


class MyState(GraphState):
    messages: Annotated[list, operator.add]


# Define nodes
responder = agent(
    model="deepseek",
    system_prompt="You are a helpful assistant.",
)

# Build graph
g = JoyGraph(MyState)
g.add_node("responder", responder)

g.add_edge(START, "responder")
g.add_edge("responder", END)
`
