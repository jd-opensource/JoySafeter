"""Skill API schemas."""

import uuid
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class SkillFileSchema(BaseModel):
    """Skill file schema."""

    id: str
    skill_id: str
    path: str
    file_name: str
    file_type: str
    content: Optional[str] = None
    storage_type: str = "database"
    storage_key: Optional[str] = None
    size: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("id", "skill_id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string."""
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        """Convert datetime to ISO format string."""
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    class Config:
        from_attributes = True


class SkillFileCreate(BaseModel):
    """Schema for creating a skill file."""

    path: str
    file_name: str
    file_type: str
    content: Optional[str] = None
    storage_type: str = "database"
    storage_key: Optional[str] = None
    size: int = 0

    @field_validator("path")
    @classmethod
    def validate_path(cls, v):
        """Validate that the file path is not empty."""
        if not v:
            raise ValueError("File path cannot be empty")
        return v


class SkillSchema(BaseModel):
    """Skill schema for API responses."""

    id: str
    name: str
    description: str
    content: str
    tags: List[str] = Field(default_factory=list)
    source_type: str
    source_url: Optional[str] = None
    root_path: Optional[str] = None
    owner_id: Optional[str] = None
    created_by_id: str
    is_public: bool = False
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: dict = Field(default_factory=dict, validation_alias="meta_data")
    allowed_tools: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    files: Optional[List[SkillFileSchema]] = None

    @field_validator("id", mode="before")
    @classmethod
    def convert_uuid_to_str(cls, v):
        """Convert UUID to string."""
        if isinstance(v, uuid.UUID):
            return str(v)
        return v

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def convert_datetime_to_str(cls, v):
        """Convert datetime to ISO format string."""
        if isinstance(v, datetime):
            return v.isoformat()
        return v

    @model_validator(mode="before")
    @classmethod
    def map_meta_data_from_attributes(cls, data):
        """Map meta_data attribute to metadata field when using from_attributes."""
        if not isinstance(data, dict) and hasattr(data, "meta_data"):
            # For SQLAlchemy models: convert to dict and map meta_data -> metadata
            # Pydantic will handle the rest via from_attributes
            data_dict = {}
            # Get all SQLAlchemy mapped attributes
            mapper = getattr(data.__class__, "__mapper__", None)
            if mapper:
                for key in mapper.columns.keys():
                    if key == "meta_data":
                        data_dict["metadata"] = getattr(data, key, {})
                    else:
                        data_dict[key] = getattr(data, key, None)
            # Also get relationships and other attributes
            for key in ["id", "created_at", "updated_at", "files"]:
                if hasattr(data, key):
                    data_dict[key] = getattr(data, key)
            # Ensure meta_data is mapped to metadata
            if hasattr(data, "meta_data"):
                data_dict["metadata"] = getattr(data, "meta_data")
            return data_dict
        elif isinstance(data, dict) and "meta_data" in data:
            data["metadata"] = data.pop("meta_data")
        return data

    class Config:
        from_attributes = True
        populate_by_name = True  # Allow both field name and alias


class SkillCreate(BaseModel):
    """Schema for creating a skill."""

    name: str = Field(..., max_length=64)
    description: str = Field(..., max_length=1024)
    content: str
    tags: Optional[List[str]] = Field(default_factory=list)
    source_type: str = Field(default="local", max_length=50)
    source_url: Optional[str] = None
    root_path: Optional[str] = None
    owner_id: Optional[str] = None
    is_public: bool = False
    license: Optional[str] = None
    compatibility: Optional[str] = Field(None, max_length=500)
    metadata: Optional[dict] = Field(default_factory=dict)
    allowed_tools: Optional[List[str]] = Field(default_factory=list)
    files: Optional[List[SkillFileCreate]] = None


class SkillUpdate(BaseModel):
    """Schema for updating a skill."""

    name: Optional[str] = Field(None, max_length=64)
    description: Optional[str] = Field(None, max_length=1024)
    content: Optional[str] = None
    tags: Optional[List[str]] = None
    source_type: Optional[str] = Field(None, max_length=50)
    source_url: Optional[str] = None
    root_path: Optional[str] = None
    owner_id: Optional[str] = None
    is_public: Optional[bool] = None
    license: Optional[str] = None
    compatibility: Optional[str] = Field(None, max_length=500)
    metadata: Optional[dict] = None
    allowed_tools: Optional[List[str]] = None
    files: Optional[List[SkillFileCreate]] = None  # Files to sync (replaces existing files)


class SkillFileUpdate(BaseModel):
    """Schema for updating a skill file (rename or content update)."""

    path: Optional[str] = None
    file_name: Optional[str] = None
    content: Optional[str] = None
