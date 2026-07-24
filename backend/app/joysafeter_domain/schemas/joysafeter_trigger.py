"""Pydantic schemas for unified agent triggers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.joysafeter_domain.triggers.definition import CronTriggerConfig, WebhookTriggerConfig


def _strip_required(value: str) -> str:
    return value.strip()


def _strip_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class TriggerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: Literal["cron", "webhook"] = "webhook"
    agent_id: uuid.UUID
    prompt_template: str = Field(min_length=1)
    system_prompt: Optional[str] = None
    environment_ref: Optional[str] = None
    description: Optional[str] = None
    enabled: bool = True
    session_mode: Literal["fresh", "reuse", "pinned"] = "fresh"
    pinned_session_id: Optional[uuid.UUID] = None
    filter: dict[str, Any] = Field(default_factory=dict)
    timeout_sec: int = Field(default=7200, ge=1)
    max_retries: int = Field(default=2, ge=0)

    cron_expr: Optional[str] = None
    timezone: str = "UTC"
    concurrency_policy: Literal["allow", "forbid", "replace"] = "allow"

    secret_ref: Optional[str] = None
    secret_key: str = "WEBHOOK_SECRET"
    auth_methods: list[Literal["hmac", "bearer", "token"]] = Field(default_factory=lambda: ["hmac", "bearer", "token"])
    dedupe_header: Optional[str] = "x-joysafeter-delivery"

    @field_validator("name", "type", "prompt_template", "session_mode", "timezone", "concurrency_policy", mode="before")
    @classmethod
    def _strip_required_string(cls, value: object) -> object:
        if isinstance(value, str):
            return _strip_required(value)
        return value

    @field_validator("system_prompt", "environment_ref", "description", "cron_expr", "secret_ref", "secret_key", "dedupe_header", mode="before")
    @classmethod
    def _strip_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return _strip_optional(value)
        return value

    @model_validator(mode="after")
    def _valid_trigger(self) -> "TriggerCreateRequest":
        if self.session_mode == "pinned" and self.pinned_session_id is None:
            raise ValueError("pinned_session_id is required when session_mode is pinned")
        if self.type == "cron":
            if not self.cron_expr:
                raise ValueError("cron_expr is required when type is cron")
            CronTriggerConfig.model_validate(
                {
                    "cron_expr": self.cron_expr,
                    "timezone": self.timezone,
                    "concurrency_policy": self.concurrency_policy,
                }
            )
        if self.type == "webhook":
            if not self.secret_ref:
                raise ValueError("secret_ref is required when type is webhook")
            WebhookTriggerConfig.model_validate(
                {
                    "secret_ref": self.secret_ref,
                    "secret_key": self.secret_key,
                    "auth_methods": self.auth_methods,
                    "dedupe_header": self.dedupe_header,
                }
            )
        return self


class TriggerUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    prompt_template: Optional[str] = Field(default=None, min_length=1)
    system_prompt: Optional[str] = None
    environment_ref: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    session_mode: Optional[Literal["fresh", "reuse", "pinned"]] = None
    pinned_session_id: Optional[uuid.UUID] = None
    filter: Optional[dict[str, Any]] = None
    timeout_sec: Optional[int] = Field(default=None, ge=1)
    max_retries: Optional[int] = Field(default=None, ge=0)

    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    concurrency_policy: Optional[Literal["allow", "forbid", "replace"]] = None

    secret_ref: Optional[str] = None
    secret_key: Optional[str] = None
    auth_methods: Optional[list[Literal["hmac", "bearer", "token"]]] = None
    dedupe_header: Optional[str] = None

    @field_validator("name", "prompt_template", "session_mode", "timezone", "concurrency_policy", mode="before")
    @classmethod
    def _strip_required_string(cls, value: object) -> object:
        if isinstance(value, str):
            return _strip_required(value)
        return value

    @field_validator("system_prompt", "environment_ref", "description", "cron_expr", "secret_ref", "secret_key", "dedupe_header", mode="before")
    @classmethod
    def _strip_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return _strip_optional(value)
        return value

    @model_validator(mode="after")
    def _reject_null_for_non_nullable_updates(self) -> "TriggerUpdateRequest":
        non_nullable = {
            "name",
            "prompt_template",
            "enabled",
            "session_mode",
            "filter",
            "timeout_sec",
            "max_retries",
            "timezone",
            "concurrency_policy",
            "secret_ref",
            "secret_key",
            "auth_methods",
        }
        for field in non_nullable & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TriggerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str]
    type: Literal["cron", "webhook", "manual"]
    agent_id: uuid.UUID
    prompt_template: str
    system_prompt: Optional[str]
    environment_ref: Optional[str]
    enabled: bool
    session_mode: str
    pinned_session_id: Optional[uuid.UUID]
    reusable_session_id: Optional[uuid.UUID]
    filter: dict[str, Any]
    config: dict[str, Any]
    timeout_sec: int
    max_retries: int
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    concurrency_policy: Optional[str] = None
    next_run_at: Optional[datetime] = None
    last_fired_slot: Optional[datetime] = None
    secret_ref: Optional[str] = None
    secret_key: Optional[str] = None
    project_id: Optional[str]
    webhook_url: Optional[str] = None
    last_attempt_at: Optional[datetime]
    last_success_at: Optional[datetime]
    last_error: Optional[str]
    consecutive_failures: int
    last_task_id: Optional[uuid.UUID]
    last_session_id: Optional[uuid.UUID]
    last_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @field_serializer("id")
    def _serialize_id(self, value: uuid.UUID) -> str:
        return f"trig_{value}"

    @field_serializer("agent_id", "pinned_session_id", "reusable_session_id", "last_task_id", "last_session_id")
    def _serialize_uuid(self, value: Optional[uuid.UUID]) -> Optional[str]:
        if value is None:
            return None
        return str(value)


class TriggerFireResponse(BaseModel):
    status: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    deduped: bool = False
    reason: Optional[str] = None
