"""
Pydantic schemas for AgentRelease API.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.core.contracts.agent import RuntimeKindLiteral
from app.core.contracts.execution import ReleaseStatusLiteral

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CreateAgentReleaseRequest(BaseModel):
    agent_version_id: uuid.UUID
    runtime_kind: RuntimeKindLiteral
    builder_kind: Optional[str] = None
    runtime_binding: dict = {}


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class AgentReleaseSummary(BaseModel):
    id: uuid.UUID
    release_number: int
    status: ReleaseStatusLiteral
    runtime_kind: str

    model_config = {"from_attributes": True}


class AgentReleaseResponse(BaseModel):
    id: uuid.UUID
    agent_version_id: uuid.UUID
    release_number: int
    status: ReleaseStatusLiteral
    runtime_kind: str
    builder_kind: Optional[str] = None
    executable_ref: Optional[dict] = None
    runtime_binding: dict
    published_by: Optional[str] = None
    published_at: Optional[datetime] = None
    retired_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
