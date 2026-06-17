import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


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

    @field_validator("files")
    @classmethod
    def validate_file_paths(cls, v: Optional[list[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
        if not v:
            return v
        from pathlib import PurePosixPath
        for f in v:
            path = f.get("path", "")
            if path:
                p = PurePosixPath(path)
                if p.is_absolute():
                    raise ValueError(f"Skill file path must be relative: {path}")
                if ".." in p.parts:
                    raise ValueError(f"Skill file path must not contain '..': {path}")
        return v


class UpdateSkillRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    is_public: Optional[bool] = None
    license: Optional[str] = None


class SkillSecurityScanSummary(BaseModel):
    status: str = "not_scanned"
    score: Optional[int] = None
    severity: Optional[str] = None
    recommendation: Optional[str] = None
    issues_count: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    scanned_at: Optional[datetime] = None
    scan_id: Optional[uuid.UUID] = None
    target_hash: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("scan_id")
    def serialize_scan_id(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"sklscan_{v}" if v else None


class SkillSecurityScanResponse(BaseModel):
    id: uuid.UUID
    skill_id: Optional[uuid.UUID] = None
    project_id: Optional[str] = None
    owner_id: Optional[str] = None
    created_by_id: str
    trigger: str
    target_name: Optional[str] = None
    target_hash: str
    scanner: str = "skillspector"
    scanner_version: Optional[str] = None
    status: str
    score: Optional[int] = None
    severity: Optional[str] = None
    recommendation: Optional[str] = None
    issues_count: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    report: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"sklscan_{v}"

    @field_serializer("skill_id")
    def serialize_skill_id(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"skill_{v}" if v else None


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
    security_scan: SkillSecurityScanSummary = Field(default_factory=SkillSecurityScanSummary)
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

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        from pathlib import PurePosixPath
        p = PurePosixPath(v)
        if p.is_absolute():
            raise ValueError("Skill file path must be relative")
        if ".." in p.parts:
            raise ValueError("Skill file path must not contain '..'")
        return v


class UpdateSkillFileRequest(BaseModel):
    path: Optional[str] = None
    file_name: Optional[str] = None
    content: Optional[str] = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from pathlib import PurePosixPath
        p = PurePosixPath(v)
        if p.is_absolute():
            raise ValueError("Skill file path must be relative")
        if ".." in p.parts:
            raise ValueError("Skill file path must not contain '..'")
        return v


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
