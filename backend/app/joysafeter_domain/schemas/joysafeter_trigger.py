"""Pydantic schemas for unified agent triggers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.joysafeter_shared.ids import AgentId, CredentialId, EnvironmentId, ProjectId, SessionId, TaskId, TriggerId


def _strip_required(value: str) -> str:
    return value.strip()


def _strip_optional(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class TriggerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    type: str = "webhook"
    agent_id: AgentId
    prompt_template: str = Field(min_length=1)
    environment_id: Optional[EnvironmentId] = None
    description: Optional[str] = None
    enabled: bool = True
    session_mode: str = "fresh"
    pinned_session_id: Optional[SessionId] = None
    session_key: Optional[str] = None
    filter: dict[str, Any] = Field(default_factory=dict)
    timeout_sec: int = Field(default=7200, ge=1)
    max_retries: int = Field(default=2, ge=0)

    cron_expr: Optional[str] = None
    timezone: str = "UTC"
    run_at: Optional[datetime] = None
    concurrency_policy: str = "allow"

    webhook_auth_credential_id: Optional[CredentialId] = None
    webhook_auth_field: Optional[str] = "WEBHOOK_SECRET"
    auth_methods: Optional[list[str]] = None
    dedupe_header: Optional[str] = "x-joysafeter-delivery"

    @field_validator("name", "type", "prompt_template", "session_mode", "timezone", "concurrency_policy", mode="before")
    @classmethod
    def _strip_required_string(cls, value: object) -> object:
        if isinstance(value, str):
            return _strip_required(value)
        return value

    @field_validator(
        "description",
        "cron_expr",
        "webhook_auth_field",
        "dedupe_header",
        "session_key",
        mode="before",
    )
    @classmethod
    def _strip_optional_string(cls, value: object) -> object:
        if isinstance(value, str):
            return _strip_optional(value)
        return value


class TriggerUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    prompt_template: Optional[str] = Field(default=None, min_length=1)
    environment_id: Optional[EnvironmentId] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    session_mode: Optional[str] = None
    pinned_session_id: Optional[SessionId] = None
    session_key: Optional[str] = None
    filter: Optional[dict[str, Any]] = None
    timeout_sec: Optional[int] = Field(default=None, ge=1)
    max_retries: Optional[int] = Field(default=None, ge=0)

    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    run_at: Optional[datetime] = None
    concurrency_policy: Optional[str] = None

    webhook_auth_credential_id: Optional[CredentialId] = None
    webhook_auth_field: Optional[str] = None
    auth_methods: Optional[list[str]] = None
    dedupe_header: Optional[str] = None

    @field_validator("name", "prompt_template", "session_mode", "timezone", "concurrency_policy", mode="before")
    @classmethod
    def _strip_required_string(cls, value: object) -> object:
        if isinstance(value, str):
            return _strip_required(value)
        return value

    @field_validator(
        "description",
        "cron_expr",
        "webhook_auth_field",
        "dedupe_header",
        "session_key",
        mode="before",
    )
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
            "auth_methods",
        }
        for field in non_nullable & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TriggerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: TriggerId
    name: str
    description: Optional[str]
    type: Literal["cron", "webhook", "manual"]
    agent_id: AgentId
    prompt_template: str
    environment_id: Optional[EnvironmentId]
    enabled: bool
    session_mode: str
    pinned_session_id: Optional[SessionId]
    reusable_session_id: Optional[SessionId]
    session_key: Optional[str] = None
    filter: dict[str, Any]
    config: dict[str, Any]
    timeout_sec: int
    max_retries: int
    cron_expr: Optional[str] = None
    timezone: Optional[str] = None
    run_at: Optional[datetime] = None
    concurrency_policy: Optional[str] = None
    next_run_at: Optional[datetime] = None
    last_fired_slot: Optional[datetime] = None
    webhook_auth_credential_id: Optional[CredentialId] = None
    webhook_auth_field: Optional[str] = None
    project_id: ProjectId | None
    webhook_url: Optional[str] = None
    last_attempt_at: Optional[datetime]
    last_success_at: Optional[datetime]
    last_error: Optional[str]
    consecutive_failures: int
    auto_disabled_at: Optional[datetime] = None
    disabled_reason: Optional[str] = None
    last_task_id: Optional[TaskId]
    last_session_id: Optional[SessionId]
    last_payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class TriggerVariable(BaseModel):
    path: str
    token: str
    description: str
    sample: Optional[Any] = None


class TriggerVariableCatalogResponse(BaseModel):
    variables: dict[Literal["cron", "webhook", "manual"], list[TriggerVariable]]


class TriggerFireResponse(BaseModel):
    status: str
    task_id: Optional[TaskId] = None
    session_id: Optional[SessionId] = None
    deduped: bool = False
    reason: Optional[str] = None


class TriggerRunResponse(BaseModel):
    """One execution (task) fired by a trigger, for the /runs history view."""

    model_config = ConfigDict(from_attributes=True)

    id: TaskId
    trigger_id: Optional[TriggerId]
    status: str
    retry_count: int
    max_retries: int
    chat_session_id: Optional[SessionId]
    error: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
