"""Pydantic schemas for One Person Security Dept."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SecurityDeptTaskCreateRequest(BaseModel):
    """Request payload for creating a Security Dept task."""

    scenario: Literal["pentest"] = Field(default="pentest")
    target: Optional[str] = Field(default=None, max_length=5000)
    instruction: str = Field(..., min_length=1, max_length=30000)
    skill_names: list[str] = Field(default_factory=list)
    workspace_id: Optional[uuid.UUID] = Field(default=None)
    profile: str = Field(default="pentest_full_access_v1", max_length=100)


class SecurityDeptTaskResponse(BaseModel):
    """Serialized task response."""

    id: str
    user_id: str
    workspace_id: Optional[str]
    scenario: str
    profile: str
    status: str
    target: Optional[str]
    instruction_preview: str
    selected_skills: list[str]
    summary_md: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    token_usage: Optional[dict[str, Any]]
    cost_usd: Optional[float]
    execution_stats: Optional[dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class SecurityDeptTaskListResponse(BaseModel):
    items: list[SecurityDeptTaskResponse]
    total: int
    page: int
    page_size: int


class SecurityDeptCreateTaskResponse(BaseModel):
    task_id: str
    status: str
    created_at: datetime


class SecurityDeptCancelTaskResponse(BaseModel):
    task_id: str
    status: str


class SecurityDeptSkillFsItem(BaseModel):
    skill_name: str
    display_name: str
    description: str
    has_skill_md: bool
    abs_path: str


class SecurityDeptSkillFsResponse(BaseModel):
    items: list[SecurityDeptSkillFsItem]
    root_path: str


class SecurityDeptProfileItem(BaseModel):
    name: str
    description: str
    permission_mode: str
    scenario: str


class SecurityDeptProfilesResponse(BaseModel):
    items: list[SecurityDeptProfileItem]


class SecurityDeptHealthResponse(BaseModel):
    enabled: bool
    redis_available: bool
    sdk_installed: bool
    cli_found: bool
    configured_cli_path: Optional[str]
    max_concurrent_tasks: int
    timeout_seconds: int
    workdir_root: str


class SecurityDeptStreamEvent(BaseModel):
    type: str
    task_id: str
    timestamp: int
    data: dict[str, Any]
