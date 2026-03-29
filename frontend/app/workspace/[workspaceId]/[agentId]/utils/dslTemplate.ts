/**
 * Starter template for new code-mode graphs.
 * Standard LangGraph Python — no custom SDK needed.
 */
export const DSL_STARTER_TEMPLATE = `from langgraph.graph import StateGraph, START, END
from typing import TypedDict, Annotated
from langchain_core.messages import add_messages


class State(TypedDict):
    messages: Annotated[list, add_messages]


def assistant(state: State):
    # Your logic here
    return {"messages": state["messages"]}


graph = StateGraph(State)
graph.add_node("assistant", assistant)

graph.add_edge(START, "assistant")
graph.add_edge("assistant", END)
`
