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
    license: str = ""
    files: Optional[list[dict[str, Any]]] = None

    @field_validator("source_url")
    @classmethod
    def trim_source_url(cls, v: str) -> str:
        return v.strip()

    @field_validator("files")
    @classmethod
    def validate_file_paths(cls, v: Optional[list[dict[str, Any]]]) -> Optional[list[dict[str, Any]]]:
        if not v:
            return v
        from pathlib import PurePosixPath

        for f in v:
            path = f.get("path", "")
            if path:
                # Normalize Windows-style separators BEFORE the parts
                # check. Without this, ``..\\etc\\passwd`` would slip
                # through (PurePosixPath wouldn't split on backslash),
                # then be expanded later — defense-in-depth at the
                # boundary saves the row from ever landing with a
                # traversal-shaped path.
                normalized = path.replace("\\", "/")
                p = PurePosixPath(normalized)
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
    license: Optional[str] = None

    @field_validator("source_url")
    @classmethod
    def trim_source_url(cls, v: Optional[str]) -> Optional[str]:
        return v.strip() if v is not None else v


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
    visibility: str = "project"
    lifecycle_status: str = "draft"
    # Most recently published version string, or ``None`` if the skill has
    # never been published. The agent-builder skill picker hides rows where
    # this is null (can't reference an unpublished skill).
    latest_version: Optional[str] = None
    # Tier pointers: the version currently served at the organization / public
    # tier (set only through the promotion approval flow). ``None`` when the
    # skill is not exposed at that tier.
    org_version_id: Optional[uuid.UUID] = None
    public_version_id: Optional[uuid.UUID] = None
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

    @field_serializer("org_version_id", "public_version_id")
    def serialize_version_pointer(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"sklver_{v}" if v else None


class CreateSkillFileRequest(BaseModel):
    path: str
    file_name: str
    content: str = ""
    file_type: Optional[str] = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, v: str) -> str:
        from pathlib import PurePosixPath

        # Normalize Windows-style separators first (P2.14).
        normalized = v.replace("\\", "/")
        p = PurePosixPath(normalized)
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

        # Normalize Windows-style separators first (P2.14).
        normalized = v.replace("\\", "/")
        p = PurePosixPath(normalized)
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


class SkillLifecycleTransitionResponse(BaseModel):
    """Result of a lifecycle transition.

    Returned by ``submit-review`` / ``approve`` / ``reject`` / ``archive`` /
    ``unarchive`` / ``reopen``. The client uses ``to_status`` to refresh
    its local view; ``from_status`` is informational (lets the UI show
    "moved from X to Y").
    """

    skill_id: uuid.UUID
    from_status: str
    to_status: str

    model_config = ConfigDict(from_attributes=True)

    @field_serializer("skill_id")
    def serialize_skill_id(self, v: uuid.UUID) -> str:
        return f"skill_{v}"


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
