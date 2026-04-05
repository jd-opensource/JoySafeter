"""
Graph deployment version schemas
"""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GraphDeploymentVersionResponse(BaseModel):
    """Graph deployment version response."""

    id: uuid.UUID
    version: int
    name: Optional[str] = None
    is_active: bool
    created_at: datetime
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class GraphDeploymentVersionResponseCamel(BaseModel):
    """Graph deployment version response -- camelCase field names."""

    id: str
    version: int
    name: Optional[str] = None
    isActive: bool
    createdAt: str
    createdBy: Optional[str] = None
    createdByName: Optional[str] = None  # creator username

    class Config:
        from_attributes = True


class GraphDeploymentVersionStateResponse(BaseModel):
    """Graph deployment version state response -- includes full nodes, edges, etc."""

    id: str
    version: int
    name: Optional[str] = None
    isActive: bool
    createdAt: str
    createdBy: Optional[str] = None
    # full graph state; frontend can use this for preview
    state: dict = Field(default_factory=dict, description="full version state (nodes, edges, variables)")

    class Config:
        from_attributes = True


class GraphDeploymentVersionListResponse(BaseModel):
    """Graph deployment version list response (paginated)."""

    versions: List[GraphDeploymentVersionResponseCamel]
    total: int
    page: int = Field(default=1, description="current page")
    pageSize: int = Field(default=10, description="page size")
    totalPages: int = Field(default=1, description="total pages")


class GraphDeployRequest(BaseModel):
    """Deploy graph request."""

    name: Optional[str] = Field(None, description="version name (optional)")


class GraphDeployResponse(BaseModel):
    """Deploy graph response."""

    success: bool
    message: str
    version: int
    isActive: bool
    needsRedeployment: bool = Field(default=False, description="whether redeployment is needed")


class GraphRevertResponse(BaseModel):
    """Revert version response."""

    success: bool
    message: str
    version: int
    is_active: bool


class GraphRenameVersionRequest(BaseModel):
    """Rename version request."""

    name: str = Field(..., min_length=1, max_length=255, description="new version name")
