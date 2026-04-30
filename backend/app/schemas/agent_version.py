"""
Pydantic schemas for AgentVersion API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.core.contracts.agent import EngineKind

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateAgentVersionRequest(BaseModel):
    source_kind: Optional[str] = "manual"
    engine_kind: EngineKind = "langgraph_visual"
    definition_payload: Optional[Dict[str, Any]] = None
    capability_manifest: Optional[Dict[str, Any]] = None
    changelog: Optional[str] = None


class UpdateAgentVersionRequest(BaseModel):
    definition_payload: Optional[Dict[str, Any]] = None
    capability_manifest: Optional[Dict[str, Any]] = None
    changelog: Optional[str] = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AgentVersionSummary(BaseModel):
    id: uuid.UUID
    version_number: int
    status: str
    engine_kind: str

    model_config = {"from_attributes": True}


class AgentVersionResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    version_number: int
    status: str
    source_kind: str
    engine_kind: str
    definition_payload: Dict[str, Any]
    capability_manifest: Dict[str, Any]
    changelog: Optional[str] = None
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}
