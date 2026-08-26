"""Webhook trigger provider."""

from __future__ import annotations

from typing import Any

from app.joysafeter_shared.ids import CredentialId

from .base import register, stable_external_idempotency_component


class WebhookTriggerProvider:
    kind = "webhook"

    def build_config(self, **fields: Any) -> dict[str, Any]:
        credential_id = fields.get("webhook_auth_credential_id")
        if credential_id is not None and not isinstance(credential_id, CredentialId):
            raise TypeError("webhook auth credential ID must be CredentialId")
        return {
            "webhook_auth_credential_id": str(credential_id) if credential_id is not None else None,
            "webhook_auth_field": fields.get("webhook_auth_field") or "WEBHOOK_SECRET",
            "auth_methods": fields.get("auth_methods"),
            "dedupe_header": fields.get("dedupe_header") or "x-joysafeter-delivery",
        }

    def idempotency_key(self, trigger: Any, **context: Any) -> str:
        delivery_key: str = context["delivery_key"]
        delivery_component = stable_external_idempotency_component(delivery_key)
        return f"trigger:webhook:{trigger.id}:{delivery_component}"

    def build_payload(self, trigger: Any, **context: Any) -> dict[str, Any]:
        # Webhook payloads are assembled from the inbound HTTP request in the API
        # route (body/headers are request-specific); the provider passes the
        # already-built payload through so all three fire paths share one seam.
        return context.get("payload") or {}


register(WebhookTriggerProvider())
