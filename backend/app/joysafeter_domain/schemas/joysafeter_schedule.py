"""Pydantic schemas for the schedules API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.joysafeter_shared.utils.cron import validate_cron, validate_timezone


class ScheduleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    agent_id: uuid.UUID
    prompt: str = Field(min_length=1)
    cron_expr: str
    timezone: str = "UTC"
    system_prompt: Optional[str] = None
    environment_ref: Optional[str] = None
    description: Optional[str] = None
    timeout_sec: int = Field(default=7200, ge=1)
    max_retries: int = Field(default=2, ge=0)
    concurrency_policy: str = "allow"
    enabled: bool = True

    @field_validator("cron_expr")
    @classmethod
    def _valid_cron(cls, v: str) -> str:
        if not validate_cron(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        if not validate_timezone(v):
            raise ValueError(f"Invalid timezone: {v}")
        return v

    @field_validator("concurrency_policy")
    @classmethod
    def _valid_policy(cls, v: str) -> str:
        if v not in ("allow", "forbid", "replace"):
            raise ValueError("concurrency_policy must be one of: allow, forbid, replace")
        return v


class ScheduleUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    prompt: Optional[str] = None
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    system_prompt: Optional[str] = None
    environment_ref: Optional[str] = None
    description: Optional[str] = None
    timeout_sec: Optional[int] = Field(default=None, ge=1)
    max_retries: Optional[int] = Field(default=None, ge=0)
    concurrency_policy: Optional[str] = None
    enabled: Optional[bool] = None

    @field_validator("cron_expr")
    @classmethod
    def _valid_cron(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not validate_cron(v):
            raise ValueError(f"Invalid cron expression: {v}")
        return v

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not validate_timezone(v):
            raise ValueError(f"Invalid timezone: {v}")
        return v

    @field_validator("concurrency_policy")
    @classmethod
    def _valid_policy(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("allow", "forbid", "replace"):
            raise ValueError("concurrency_policy must be one of: allow, forbid, replace")
        return v


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str]
    agent_id: uuid.UUID
    prompt: str
    system_prompt: Optional[str]
    environment_ref: Optional[str]
    cron_expr: str
    timezone: str
    enabled: bool
    concurrency_policy: str
    timeout_sec: int
    max_retries: int
    next_run_at: Optional[datetime]
    last_fired_slot: Optional[datetime]
    project_id: Optional[str]
    created_at: datetime
    updated_at: datetime


class ScheduleRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    schedule_id: Optional[uuid.UUID]
    status: str
    chat_session_id: Optional[uuid.UUID]
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class TriggerResponse(BaseModel):
    task_id: uuid.UUID
    session_id: uuid.UUID
    status: str
