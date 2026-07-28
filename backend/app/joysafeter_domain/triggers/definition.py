"""Unified agent trigger config models for cron and webhook validation.

The trigger *kind* / *session mode* / *concurrency policy* enums are the model
enums (single source of truth); they are re-exported here under their historical
``AgentTrigger*`` names for callers that import them from this module.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.joysafeter_domain.models.joysafeter_trigger import (
    TriggerConcurrencyPolicy as AgentTriggerConcurrencyPolicy,
)
from app.joysafeter_domain.models.joysafeter_trigger import (
    TriggerSessionMode as AgentTriggerSessionMode,
)
from app.joysafeter_domain.models.joysafeter_trigger import (
    TriggerType as AgentTriggerKind,
)
from app.joysafeter_shared.utils.cron import validate_cron, validate_timezone

__all__ = [
    "AgentTriggerConcurrencyPolicy",
    "AgentTriggerKind",
    "AgentTriggerSessionMode",
    "CronTriggerConfig",
    "WebhookTriggerConfig",
]


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
