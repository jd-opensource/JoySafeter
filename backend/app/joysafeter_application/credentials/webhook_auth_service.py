from __future__ import annotations

import hashlib
import hmac
import json
import shlex
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.credentials.bindings import WebhookAuthBinding, WebhookAuthMethod
from app.joysafeter_domain.credentials.types import CredentialFieldName
from app.joysafeter_domain.services.credential_binding_errors import raise_public_credential_error
from app.joysafeter_shared.common.app_errors import RequestValidationAppError
from app.joysafeter_shared.ids import CredentialId, ProjectId, TriggerId

from .composition import compose_credential_application
from .ports import CredentialAccessContext, CredentialAuditActor

_WEBHOOK_AUTH_METHODS = frozenset({"hmac", "bearer", "token"})


class WebhookAuthService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        audit_actor: CredentialAuditActor,
    ) -> None:
        self.db = db
        self._audit_actor = audit_actor

    @staticmethod
    def sign(secret: str, body: bytes) -> str:
        return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    @staticmethod
    def verify_signature(raw_body: bytes, secret: str, signature_header: Optional[str]) -> bool:
        if not signature_header:
            return False
        signature = signature_header.strip()
        if signature.startswith("sha256="):
            signature = signature.removeprefix("sha256=")
        if len(signature) != 64:
            return False
        expected = WebhookAuthService.sign(secret, raw_body)
        return hmac.compare_digest(signature.lower(), expected.lower())

    @staticmethod
    def verify_token(secret: str, token: Optional[str]) -> bool:
        return bool(token) and hmac.compare_digest(token or "", secret)

    @staticmethod
    def auth_methods(config: Any) -> frozenset[str]:
        if not isinstance(config, dict):
            return frozenset()
        configured = config.get("auth_methods")
        if not isinstance(configured, list) or not configured:
            return frozenset()
        normalized: set[str] = set()
        for method in configured:
            if not isinstance(method, str):
                return frozenset()
            normalized_method = method.strip().lower()
            if normalized_method not in _WEBHOOK_AUTH_METHODS:
                return frozenset()
            normalized.add(normalized_method)
        return frozenset(normalized)

    @classmethod
    def verify_with_secret(
        cls,
        *,
        config: Any,
        raw_body: bytes,
        secret: str,
        signature: Optional[str],
        token: Optional[str],
    ) -> bool:
        methods = cls.auth_methods(config)
        if "hmac" in methods and cls.verify_signature(raw_body, secret, signature):
            return True
        if ({"bearer", "token"} & methods) and cls.verify_token(secret, token):
            return True
        return False

    async def resolve_secret_value(
        self,
        *,
        webhook_auth_credential_id: CredentialId,
        webhook_auth_field: str,
        project_id: Optional[ProjectId],
        trigger_id: Optional[TriggerId] = None,
        auth_methods: object | None = None,
    ) -> str:
        context: dict[str, Any] = {"webhook_auth_credential_id": str(webhook_auth_credential_id)}
        if trigger_id is not None:
            context["trigger_id"] = str(trigger_id)
        if project_id is None:
            raise_public_credential_error(LookupError(), credential_id=webhook_auth_credential_id)
        application = compose_credential_application(
            self.db,
            auto_commit=False,
            audit_actor=self._audit_actor,
        )
        try:
            methods = ("hmac", "bearer") if auth_methods is None else auth_methods
            normalized_methods = frozenset(
                WebhookAuthMethod.BEARER if method in {"bearer", "token"} else WebhookAuthMethod(method)
                for method in methods
            )
        except (TypeError, ValueError) as exc:
            raise_public_credential_error(exc, credential_id=webhook_auth_credential_id)
        try:
            credential_field = CredentialFieldName(webhook_auth_field)
        except (TypeError, ValueError) as exc:
            raise_public_credential_error(
                exc,
                credential_id=webhook_auth_credential_id,
                constructor_error="field_missing",
            )
        try:
            binding = WebhookAuthBinding(
                project_id=project_id,
                credential_id=webhook_auth_credential_id,
                credential_field=credential_field,
                methods=normalized_methods,
            )
            material = await application.material_access_service.resolve(
                binding,
                context=CredentialAccessContext(
                    consumer_type="webhook_auth",
                    consumer_id=str(trigger_id) if trigger_id is not None else None,
                    actor=self._audit_actor,
                ),
            )
            secret_value = material.fields[credential_field]
        except Exception as exc:
            raise_public_credential_error(exc, credential_id=webhook_auth_credential_id)
        if not secret_value.strip():
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_VALUE_BLANK",
                message="Webhook credential field must not be blank",
                data={**context, "webhook_auth_field": webhook_auth_field},
                user_action="fix_input",
            )
        return secret_value

    async def resolve_webhook_secret(self, trigger: Any) -> str:
        if not trigger.webhook_auth_credential_id:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_REF_REQUIRED",
                message="Webhook trigger requires webhook_auth_credential_id",
                data={"trigger_id": str(trigger.id)},
                user_action="fix_input",
            )
        return await self.resolve_secret_value(
            webhook_auth_credential_id=trigger.webhook_auth_credential_id,
            webhook_auth_field=trigger.webhook_auth_field or "WEBHOOK_SECRET",
            project_id=trigger.project_id,
            trigger_id=trigger.id,
            auth_methods=self.auth_methods(trigger.config),
        )

    @classmethod
    def build_signed_curl(cls, *, secret: str, url: str, sample_body: Optional[dict[str, Any]] = None) -> str:
        body = json.dumps(sample_body if sample_body is not None else {"example": "payload"}, separators=(",", ":"))
        signature = cls.sign(secret, body.encode("utf-8"))
        return (
            f"curl -X POST {shlex.quote(url)} "
            f"-H {shlex.quote('Content-Type: application/json')} "
            f"-H {shlex.quote(f'X-JoySafeter-Signature: sha256={signature}')} "
            f"-d {shlex.quote(body)}"
        )
