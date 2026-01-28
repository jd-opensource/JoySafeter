"""
Copilot Action Types - Pydantic models for Copilot API.

Defines the data models used in Copilot requests and responses,
including graph actions (CREATE_NODE, CONNECT_NODES, etc.).
"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class GraphActionType(str, Enum):
    """Graph action types that can be executed by Copilot."""

    CREATE_NODE = "CREATE_NODE"
    CONNECT_NODES = "CONNECT_NODES"
    DELETE_NODE = "DELETE_NODE"
    UPDATE_CONFIG = "UPDATE_CONFIG"
    UPDATE_POSITION = "UPDATE_POSITION"


class GraphAction(BaseModel):
    """Single graph action to be executed."""

    type: GraphActionType = Field(..., description="Action type")
    payload: Dict[str, Any] = Field(..., description="Action payload")
    reasoning: str = Field(..., description="Reasoning for the action")


# ==================== Message Persistence Types ====================


class CopilotThoughtStep(BaseModel):
    """Single thought step in AI reasoning process."""

    index: int = Field(..., description="Step index (1-based)")
    content: str = Field(..., description="Thought content")


class CopilotToolCall(BaseModel):
    """Record of a tool call made by the AI."""

    tool: str = Field(..., description="Tool name")
    input: Dict[str, Any] = Field(default_factory=dict, description="Tool input parameters")
    output: Optional[Dict[str, Any]] = Field(default=None, description="Tool output (optional)")


class CopilotMessage(BaseModel):
    """Single message in Copilot conversation history."""

    id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}", description="Unique message ID")
    role: str = Field(..., description="Message role: 'user' or 'assistant'")
    content: str = Field(..., description="Message text content")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Message creation time")

    # Fields only for assistant messages
    actions: Optional[List[Dict[str, Any]]] = Field(default=None, description="Graph actions executed")
    thought_steps: Optional[List[CopilotThoughtStep]] = Field(default=None, description="AI thinking process")
    tool_calls: Optional[List[CopilotToolCall]] = Field(default=None, description="Tool calls made")


class CopilotHistoryResponse(BaseModel):
    """Response for Copilot history API."""

    graph_id: str = Field(..., description="Associated graph ID")
    messages: List[CopilotMessage] = Field(default_factory=list, description="Conversation messages")
    created_at: Optional[datetime] = Field(default=None, description="Session creation time")
    updated_at: Optional[datetime] = Field(default=None, description="Session last update time")


class CopilotRequest(BaseModel):
    """Copilot request for generating graph actions."""

    prompt: str = Field(..., description="User prompt")
    graph_context: Dict[str, Any] = Field(default_factory=dict, description="Current graph state (nodes, edges)")
    graph_id: Optional[str] = Field(default=None, description="Graph ID for history persistence")
    conversation_history: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Previous conversation messages for context. Format: [{'role': 'user'|'assistant', 'content': '...'}, ...]",
    )


class CopilotResponse(BaseModel):
    """Copilot response with message and actions."""

    message: str = Field(..., description="Chat message to the user")
    actions: List[GraphAction] = Field(default_factory=list, description="Array of actions to execute")


# ==================== Tool Call Result Types ====================


class CreateNodePayload(BaseModel):
    """Payload for CREATE_NODE action."""

    id: str = Field(..., description="Unique node ID")
    type: str = Field(..., description="Node type (agent, condition, etc.)")
    label: str = Field(..., description="Human-readable label")
    position: Dict[str, float] = Field(..., description="Node position {x, y}")
    config: Dict[str, Any] = Field(default_factory=dict, description="Node configuration")


class ConnectNodesPayload(BaseModel):
    """Payload for CONNECT_NODES action."""

    source: str = Field(..., description="Source node ID")
    target: str = Field(..., description="Target node ID")


class DeleteNodePayload(BaseModel):
    """Payload for DELETE_NODE action."""

    id: str = Field(..., description="Node ID to delete")


class UpdateConfigPayload(BaseModel):
    """Payload for UPDATE_CONFIG action."""

    id: str = Field(..., description="Node ID to update")
    config: Dict[str, Any] = Field(..., description="Configuration to merge")
