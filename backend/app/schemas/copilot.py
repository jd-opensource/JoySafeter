from typing import Any, Optional

from pydantic import BaseModel


class CopilotStreamRequest(BaseModel):
    provider_name: str
    model_name: str
    prompt: str
    graph_context: dict[str, Any]
    conversation_history: list[dict[str, Any]]
    mode: Optional[str] = None
