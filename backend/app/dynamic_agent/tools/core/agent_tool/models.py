"""Agent Tool Data Models.

This module defines the core data structures used by the agent tool:
- AgentResult: Result of Sub-Agent execution
- AgentState: State for ReAct agent loop
- _render_task: Task rendering helper

These models form the foundation of the agent tool split and have no
dependencies on other agent_tool modules (leaf node in dependency graph).
"""

from typing import Annotated, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


class AgentResult(BaseModel):
    """Result from Sub-Agent execution."""

    name: str = Field(description="Agent name")
    level: int = Field(description="Agent level")
    duration_ms: int = Field(description="Execution duration in milliseconds")
    ok: bool = Field(description="Whether execution succeeded")
    result: str = Field(description="Execution result or output")
    error: Optional[str] = Field(default=None, description="Error message if failed")


class AgentState(TypedDict):
    """State for ReAct agent loop."""

    messages: Annotated[List[BaseMessage], add_messages]


def _render_task(task_detail: str) -> str:
    """Render task for Sub-Agent execution."""
    return task_detail


__all__ = ["AgentResult", "AgentState", "_render_task"]
