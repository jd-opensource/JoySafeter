"""Webhook trigger provider."""

from __future__ import annotations

from typing import Any

from .base import register


class WebhookTriggerProvider:
    kind = "webhook"

    def build_config(self, **fields: Any) -> dict[str, Any]:
        return {
            "secret_ref": fields.get("secret_ref"),
            "secret_key": fields.get("secret_key") or "WEBHOOK_SECRET",
            "auth_methods": fields.get("auth_methods") or ["hmac", "bearer", "token"],
            "dedupe_header": fields.get("dedupe_header") or "x-joysafeter-delivery",
        }

    def idempotency_key(self, trigger: Any, **context: Any) -> str:
        delivery_key: str = context["delivery_key"]
        return f"trigger:webhook:{trigger.id}:{delivery_key}"

    def build_payload(self, trigger: Any, **context: Any) -> dict[str, Any]:
        # Webhook payloads are assembled from the inbound HTTP request in the API
        # route (body/headers are request-specific); the provider passes the
        # already-built payload through so all three fire paths share one seam.
        return context.get("payload") or {}


register(WebhookTriggerProvider())
