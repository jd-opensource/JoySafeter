import uuid
from typing import Any, Optional

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field


class ChatRequest(PydanticBaseModel):
    """Chat request."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(..., description="user message")
    thread_id: Optional[str] = Field(None, description="conversation thread ID; omit to create a new session")
    graph_id: Optional[uuid.UUID] = Field(None, description="graph ID; use the specified graph for the conversation")
    provider_name: Optional[str] = Field(None, description="model provider name (e.g. 'ollama', 'openai')")
    model_name: Optional[str] = Field(None, description="model name (e.g. 'qwen3.5:latest', 'gpt-4o')")
    metadata: dict[str, Any] = Field(default_factory=dict, description="metadata")
    # user_id is obtained from authentication; no longer needed in the request


class ChatResponse(PydanticBaseModel):
    """Chat response."""

    thread_id: str = Field(..., description="conversation thread ID")
    response: str = Field(..., description="assistant reply")
    duration_ms: int = Field(..., description="execution duration (ms)")
