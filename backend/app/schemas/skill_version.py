"""Pydantic schemas for Skill Version API."""

from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.base import ISODatetime, UUIDStr


class VersionPublishRequest(BaseModel):
    version: str = Field(..., description="Semver MAJOR.MINOR.PATCH", max_length=20)
    release_notes: Optional[str] = Field(None, description="Changelog / release notes")


class VersionRestoreRequest(BaseModel):
    version: str = Field(..., description="Version to restore draft from")


class VersionFileSchema(BaseModel):
    id: UUIDStr
    version_id: UUIDStr
    path: str
    file_name: str
    file_type: str
    content: Optional[str] = None
    storage_type: str = "database"
    storage_key: Optional[str] = None
    size: int = 0

    class Config:
        from_attributes = True


class VersionSchema(BaseModel):
    id: UUIDStr
    skill_id: UUIDStr
    version: str
    release_notes: Optional[str] = None
    skill_name: str
    skill_description: str
    content: str
    tags: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict, validation_alias="meta_data")
    allowed_tools: List[str] = Field(default_factory=list)
    compatibility: Optional[str] = None
    license: Optional[str] = None
    published_by_id: str
    published_at: ISODatetime = None
    created_at: ISODatetime = None
    files: Optional[List[VersionFileSchema]] = None

    class Config:
        from_attributes = True
        populate_by_name = True


class VersionSummarySchema(BaseModel):
    """Lightweight version info for list endpoints."""

    version: str
    release_notes: Optional[str] = None
    published_by_id: str
    published_at: ISODatetime = None

    class Config:
        from_attributes = True
