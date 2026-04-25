"""
Pydantic schemas for Agent API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Literals
# ---------------------------------------------------------------------------

AgentStatusLiteral = Literal["draft", "active", "archived"]
DefinitionKindLiteral = Literal["prompt", "graph", "code", "hybrid"]

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateAgentRequest(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    avatar: Optional[str] = None
    definition_kind: DefinitionKindLiteral = "prompt"
    definition_payload: Optional[Dict[str, Any]] = None
    capability_manifest: Optional[Dict[str, Any]] = None


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255)
    description: Optional[str] = None
    avatar: Optional[str] = None
    status: Optional[AgentStatusLiteral] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AgentSummary(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}


class AgentResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: Optional[str] = None
    avatar: Optional[str] = None
    status: str
    current_draft_version_id: Optional[uuid.UUID] = None
    active_release_id: Optional[uuid.UUID] = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
