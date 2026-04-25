import uuid
from typing import Any, Optional

from pydantic import BaseModel


class CopilotRunRequest(BaseModel):
    """Dispatch a copilot interaction through the execution engine."""
    agent_id: uuid.UUID
    prompt: str
    graph_context: dict[str, Any]
    conversation_history: list[dict[str, Any]] = []
    mode: str = "deepagents"
    provider_name: Optional[str] = None
    model_name: Optional[str] = None


class CopilotRunResponse(BaseModel):
    run_id: str
    execution_id: str
