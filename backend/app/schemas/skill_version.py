"""Pydantic schemas for Skill Version API."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class VersionPublishRequest(BaseModel):
    version: str = Field(..., description="Semver MAJOR.MINOR.PATCH", max_length=20)
    release_notes: Optional[str] = Field(None, description="Changelog / release notes")


class VersionRestoreRequest(BaseModel):
    version: str = Field(..., description="Version to restore draft from")


class VersionFileSchema(BaseModel):
    id: str
    version_id: str
    path: str
    file_name: str
    file_type: str
    content: Optional[str] = None
    storage_type: str = "database"
    storage_key: Optional[str] = None
    size: int = 0

    @field_validator("id", "version_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    class Config:
        from_attributes = True


class VersionSchema(BaseModel):
    id: str
    skill_id: str
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
    published_at: Optional[str] = None
    created_at: Optional[str] = None
    files: Optional[List[VersionFileSchema]] = None

    @field_validator("id", "skill_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("published_at", "created_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True
        populate_by_name = True


class VersionSummarySchema(BaseModel):
    """Lightweight version info for list endpoints."""
    version: str
    release_notes: Optional[str] = None
    published_at: Optional[str] = None

    @field_validator("published_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True
