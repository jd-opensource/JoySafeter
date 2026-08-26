from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.joysafeter_shared.ids import (
    AgentId,
    AgentVersionId,
    ProjectId,
    SessionId,
    SkillFileId,
    SkillId,
    SkillSecurityScanId,
    SkillUsageId,
    SkillVersionFileId,
    SkillVersionId,
    TaskId,
    TriggerId,
    UserId,
)


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
    scan_id: Optional[SkillSecurityScanId] = None
    target_hash: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class SkillReferenceSummary(BaseModel):
    agents: int = 0
    agent_versions: int = 0
    triggers: int = 0
    active_tasks: int = 0
    total: int = 0


class SkillReferenceItem(BaseModel):
    type: str
    id: AgentId | AgentVersionId | TriggerId | TaskId
    name: str
    version: Optional[str] = None
    status: Optional[str] = None


class SkillImpactSummary(BaseModel):
    counts: SkillReferenceSummary = Field(default_factory=SkillReferenceSummary)
    references: list[SkillReferenceItem] = Field(default_factory=list)


class SkillUsageResponse(BaseModel):
    id: SkillUsageId
    skill_id: Optional[SkillId] = None
    skill_name: Optional[str] = None
    skill_source_type: Optional[str] = None
    skill_version: Optional[str] = None
    skill_version_id: Optional[SkillVersionId] = None
    target: Optional[str] = None
    security_scan_id: Optional[SkillSecurityScanId] = None
    target_hash: Optional[str] = None
    artifact_hash: Optional[str] = None
    session_id: Optional[SessionId] = None
    agent_id: Optional[AgentId] = None
    project_id: Optional[ProjectId] = None
    user_id: Optional[UserId] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SkillSecurityScanResponse(BaseModel):
    id: SkillSecurityScanId
    skill_id: Optional[SkillId] = None
    project_id: Optional[ProjectId] = None
    owner_id: Optional[UserId] = None
    created_by_id: UserId
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


class SkillResponse(BaseModel):
    id: SkillId
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
    org_version_id: Optional[SkillVersionId] = None
    public_version_id: Optional[SkillVersionId] = None
    license: Optional[str] = None
    compatibility: Optional[str] = None
    metadata: dict = Field(default_factory=dict, alias="meta_data")
    allowed_tools: list = Field(default_factory=list)
    security_scan: SkillSecurityScanSummary = Field(default_factory=SkillSecurityScanSummary)
    impact: Optional[SkillImpactSummary] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


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
    id: SkillFileId
    skill_id: SkillId
    path: str
    file_name: str
    file_type: str = "text"
    content: Optional[str] = None
    size: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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

    skill_id: SkillId
    from_status: str
    to_status: str

    model_config = ConfigDict(from_attributes=True)


class SkillVersionResponse(BaseModel):
    id: SkillVersionId
    skill_id: SkillId
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
    # Promotion state (single-axis model): ``lifecycle_status`` is the version's
    # review state (approved / pending_review / rejected); when pending,
    # ``review_target_visibility`` is the tier the submission targets. The UI
    # uses these to render promotion status and gate approve/reject.
    lifecycle_status: str = "approved"
    review_target_visibility: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SkillVersionFileResponse(BaseModel):
    id: SkillVersionFileId
    version_id: SkillVersionId
    path: str
    file_name: str
    file_type: str = "text"
    content: Optional[str] = None
    size: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
