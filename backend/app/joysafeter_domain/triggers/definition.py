"""Unified agent trigger definitions for cron, webhook, and manual invocations."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

from app.joysafeter_shared.utils.cron import validate_cron, validate_timezone


class AgentTriggerKind(str, enum.Enum):
    CRON = "cron"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class AgentTriggerSessionMode(str, enum.Enum):
    FRESH = "fresh"
    REUSE = "reuse"
    PINNED = "pinned"


class AgentTriggerConcurrencyPolicy(str, enum.Enum):
    ALLOW = "allow"
    FORBID = "forbid"
    REPLACE = "replace"


class CronTriggerConfig(BaseModel):
    cron_expr: str
    timezone: str = "UTC"
    concurrency_policy: Literal["allow", "forbid", "replace"] = "allow"
    next_run_at: Optional[datetime] = None
    last_fired_slot: Optional[datetime] = None

    @field_validator("cron_expr")
    @classmethod
    def _valid_cron(cls, value: str) -> str:
        value = value.strip()
        if not validate_cron(value):
            raise ValueError(f"Invalid cron expression: {value}")
        return value

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        value = value.strip() or "UTC"
        if not validate_timezone(value):
            raise ValueError(f"Invalid timezone: {value}")
        return value


class WebhookTriggerConfig(BaseModel):
    secret_ref: str = Field(min_length=1)
    secret_key: str = "WEBHOOK_SECRET"
    auth_methods: list[Literal["hmac", "bearer", "token"]] = Field(default_factory=lambda: ["hmac", "bearer", "token"])
    dedupe_header: Optional[str] = "x-joysafeter-delivery"

    @field_validator("secret_ref", "secret_key", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("auth_methods")
    @classmethod
    def _non_empty_auth_methods(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("auth_methods must not be empty")
        return value


class AgentTriggerDefinition(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str] = None
    kind: Literal["cron", "webhook", "manual"]
    agent_id: uuid.UUID
    prompt_template: str
    system_prompt: Optional[str] = None
    environment_ref: Optional[str] = None
    enabled: bool = True
    session_mode: Literal["fresh", "reuse", "pinned"] = "fresh"
    pinned_session_id: Optional[uuid.UUID] = None
    reusable_session_id: Optional[uuid.UUID] = None
    timeout_sec: int = 7200
    max_retries: int = 2
    filter: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    project_id: Optional[str] = None
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    last_task_id: Optional[uuid.UUID] = None
    last_session_id: Optional[uuid.UUID] = None
    last_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _valid_mode_config(self) -> "AgentTriggerDefinition":
        if self.session_mode == "pinned" and self.pinned_session_id is None:
            raise ValueError("pinned_session_id is required when session_mode is pinned")
        if self.kind == "cron":
            CronTriggerConfig.model_validate(self.config)
        elif self.kind == "webhook":
            WebhookTriggerConfig.model_validate(self.config)
        return self

    @field_serializer("id", "agent_id", "pinned_session_id", "reusable_session_id", "last_task_id", "last_session_id")
    def _serialize_uuid(self, value: Optional[uuid.UUID]) -> Optional[str]:
        if value is None:
            return None
        return str(value)
