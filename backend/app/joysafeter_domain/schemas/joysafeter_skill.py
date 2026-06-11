import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class CreateSkillRequest(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)
    source_type: str = "manual"
    source_url: str = ""
    is_public: bool = False
    license: str = ""
    files: Optional[list[dict[str, Any]]] = None


class UpdateSkillRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    is_public: Optional[bool] = None
    license: Optional[str] = None


class SkillResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str = ""
    content: str = ""
    tags: list = Field(default_factory=list)
    source_type: str = "manual"
    source_url: Optional[str] = None
    is_public: bool = False
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: dict = Field(default_factory=dict, alias="meta_data")
    allowed_tools: list = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"skill_{v}"


class CreateSkillFileRequest(BaseModel):
    path: str
    file_name: str
    content: str = ""
    file_type: Optional[str] = None


class UpdateSkillFileRequest(BaseModel):
    path: Optional[str] = None
    file_name: Optional[str] = None
    content: Optional[str] = None


class SkillFileResponse(BaseModel):
    id: uuid.UUID
    skill_id: uuid.UUID
    path: str
    file_name: str
    file_type: str = "text"
    content: Optional[str] = None
    size: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"sklfile_{v}"

    @field_serializer("skill_id")
    def serialize_skill_id(self, v: uuid.UUID) -> str:
        return f"skill_{v}"


class CreateSkillVersionRequest(BaseModel):
    version: Optional[str] = None
    release_notes: str = ""


class SkillVersionResponse(BaseModel):
    id: uuid.UUID
    skill_id: uuid.UUID
    version: str
    skill_name: str = ""
    skill_description: str = ""
    content: str = ""
    tags: list = Field(default_factory=list)
    allowed_tools: list = Field(default_factory=list)
    compatibility: Optional[str] = None
    license: Optional[str] = None
    release_notes: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"sklver_{v}"

    @field_serializer("skill_id")
    def serialize_skill_id(self, v: uuid.UUID) -> str:
        return f"skill_{v}"


class SkillVersionFileResponse(BaseModel):
    id: uuid.UUID
    version_id: uuid.UUID
    path: str
    file_name: str
    file_type: str = "text"
    content: Optional[str] = None
    size: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"sklvfile_{v}"

    @field_serializer("version_id")
    def serialize_version_id(self, v: uuid.UUID) -> str:
        return f"sklver_{v}"
