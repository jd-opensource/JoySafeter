"""Manual (``POST /triggers/{id}/run``) trigger provider."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from .base import cron_block, register

# When no explicit Idempotency-Key header is supplied, collapse rapid repeat
# clicks (e.g. a double-click or an impatient retry) within this window into one
# fire. A caller who genuinely wants a second run either waits out the window or
# supplies a distinct Idempotency-Key.
_MANUAL_DEDUPE_WINDOW_SEC = 10


class ManualTriggerProvider:
    kind = "manual"

    def build_config(self, **fields: Any) -> dict[str, Any]:
        return {}

    def idempotency_key(self, trigger: Any, **context: Any) -> str:
        idempotency_header: Optional[str] = context.get("idempotency_header")
        if idempotency_header:
            return f"trigger:{trigger.id}:manual:{idempotency_header}"
        user_id: Optional[str] = context.get("user_id")
        moment = context.get("now") or datetime.now(timezone.utc)
        bucket = int(moment.timestamp()) // _MANUAL_DEDUPE_WINDOW_SEC
        return f"trigger:{trigger.id}:manual:{user_id or 'anon'}:{bucket}"

    def build_payload(self, trigger: Any, **context: Any) -> dict[str, Any]:
        moment = context.get("now") or datetime.now(timezone.utc)
        fired_at = moment.isoformat()
        return {
            "trigger": {
                "id": str(trigger.id),
                "name": trigger.name,
                "type": "manual",
                "source_type": trigger.type,
                "fired_at": fired_at,
            },
            "cron": cron_block(trigger, fired_at),
        }


register(ManualTriggerProvider())
