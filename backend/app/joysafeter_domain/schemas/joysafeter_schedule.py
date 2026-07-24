"""Pydantic schemas for the schedules API."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.joysafeter_shared.utils.cron import validate_cron, validate_timezone


def _strip_required(v: str) -> str:
    return v.strip()


def _strip_optional(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    stripped = v.strip()
    return stripped or None


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
    session_mode: str = "fresh"
    pinned_session_id: Optional[uuid.UUID] = None
    enabled: bool = True

    @field_validator("name", "prompt", "cron_expr", "timezone", "concurrency_policy", "session_mode", mode="before")
    @classmethod
    def _strip_required_string(cls, v):
        if isinstance(v, str):
            return _strip_required(v)
        return v

    @field_validator("system_prompt", "environment_ref", "description", mode="before")
    @classmethod
    def _strip_optional_string(cls, v):
        if isinstance(v, str):
            return _strip_optional(v)
        return v

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

    @field_validator("session_mode")
    @classmethod
    def _valid_session_mode(cls, v: str) -> str:
        if v not in ("fresh", "reuse", "pinned"):
            raise ValueError("session_mode must be one of: fresh, reuse, pinned")
        return v

    @model_validator(mode="after")
    def _valid_pinned_session(self) -> "ScheduleCreateRequest":
        if self.session_mode == "pinned" and self.pinned_session_id is None:
            raise ValueError("pinned_session_id is required when session_mode is pinned")
        return self


class ScheduleUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    prompt: Optional[str] = Field(default=None, min_length=1)
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    system_prompt: Optional[str] = None
    environment_ref: Optional[str] = None
    description: Optional[str] = None
    timeout_sec: Optional[int] = Field(default=None, ge=1)
    max_retries: Optional[int] = Field(default=None, ge=0)
    concurrency_policy: Optional[str] = None
    session_mode: Optional[str] = None
    pinned_session_id: Optional[uuid.UUID] = None
    enabled: Optional[bool] = None

    @field_validator("name", "prompt", "cron_expr", "timezone", "concurrency_policy", "session_mode", mode="before")
    @classmethod
    def _strip_required_string(cls, v):
        if isinstance(v, str):
            return _strip_required(v)
        return v

    @field_validator("system_prompt", "environment_ref", "description", mode="before")
    @classmethod
    def _strip_optional_string(cls, v):
        if isinstance(v, str):
            return _strip_optional(v)
        return v

    @model_validator(mode="after")
    def _reject_null_for_non_nullable_updates(self) -> "ScheduleUpdateRequest":
        non_nullable = {
            "name",
            "prompt",
            "cron_expr",
            "timezone",
            "timeout_sec",
            "max_retries",
            "concurrency_policy",
            "session_mode",
            "enabled",
        }
        for field in non_nullable & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self

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

    @field_validator("session_mode")
    @classmethod
    def _valid_session_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("fresh", "reuse", "pinned"):
            raise ValueError("session_mode must be one of: fresh, reuse, pinned")
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
    session_mode: str = "fresh"
    pinned_session_id: Optional[uuid.UUID] = None
    reusable_session_id: Optional[uuid.UUID] = None
    timeout_sec: int
    max_retries: int
    next_run_at: Optional[datetime]
    last_fired_slot: Optional[datetime]
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    last_task_id: Optional[uuid.UUID] = None
    last_session_id: Optional[uuid.UUID] = None
    last_payload: dict = Field(default_factory=dict)
    project_id: Optional[str]
    created_at: datetime
    updated_at: datetime

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"sched_{v}"

    @field_serializer("agent_id")
    def serialize_agent_id(self, v: uuid.UUID) -> str:
        return f"agent_{v}"

    @field_serializer("pinned_session_id", "reusable_session_id", "last_session_id")
    def serialize_session_id(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"sess_{v}" if v is not None else None

    @field_serializer("last_task_id")
    def serialize_last_task_id(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"task_{v}" if v is not None else None


class ScheduleRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    schedule_id: Optional[uuid.UUID]
    status: str
    retry_count: int
    max_retries: int
    chat_session_id: Optional[uuid.UUID]
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    @field_serializer("id")
    def serialize_id(self, v: uuid.UUID) -> str:
        return f"task_{v}"

    @field_serializer("schedule_id")
    def serialize_schedule_id(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"sched_{v}" if v is not None else None

    @field_serializer("chat_session_id")
    def serialize_chat_session_id(self, v: Optional[uuid.UUID]) -> Optional[str]:
        return f"sess_{v}" if v is not None else None


class TriggerResponse(BaseModel):
    task_id: uuid.UUID
    session_id: uuid.UUID
    status: str

    @field_serializer("task_id")
    def serialize_task_id(self, v: uuid.UUID) -> str:
        return f"task_{v}"

    @field_serializer("session_id")
    def serialize_session_id(self, v: uuid.UUID) -> str:
        return f"sess_{v}"
