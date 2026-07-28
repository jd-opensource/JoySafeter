"""Cron (schedule) trigger provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import register


class CronTriggerProvider:
    kind = "cron"

    def build_config(self, **fields: Any) -> dict[str, Any]:
        return {
            "cron_expr": fields.get("cron_expr"),
            "timezone": fields.get("timezone") or "UTC",
            "concurrency_policy": fields.get("concurrency_policy") or "allow",
            "next_run_at": fields.get("next_run_at"),
            "last_fired_slot": fields.get("last_fired_slot"),
        }

    def idempotency_key(self, trigger: Any, **context: Any) -> str:
        # The slot instant is the logical occurrence, so a retried tick dedups to
        # one execution per slot. A failed attempt leaves a FAILED task holding
        # the attempt-0 key, so retries (attempt > 0) must use a distinct key to
        # actually re-fire rather than dedup against the prior failure.
        fired_slot: datetime = context["fired_slot"]
        attempt = int(context.get("attempt", 0) or 0)
        slot_epoch = int(fired_slot.timestamp())
        base = f"trigger:cron:{trigger.id}:{slot_epoch}"
        return base if attempt <= 0 else f"{base}:r{attempt}"

    def build_payload(self, trigger: Any, **context: Any) -> dict[str, Any]:
        fired_slot: datetime = context["fired_slot"]
        return {
            "schedule": {
                "id": str(trigger.id),
                "name": trigger.name,
                "cron_expr": trigger.cron_expr,
                "timezone": trigger.timezone,
                "fired_at": fired_slot.isoformat(),
                "last_fired_slot": trigger.last_fired_slot.isoformat() if trigger.last_fired_slot else None,
            },
            "trigger": {"type": "cron", "source": "cron"},
        }


register(CronTriggerProvider())
