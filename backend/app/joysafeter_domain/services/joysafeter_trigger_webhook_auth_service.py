from __future__ import annotations

import hashlib
import hmac
import json
import shlex
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.schemas.joysafeter_credential import CredentialKind
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_shared.common.app_errors import NotFoundError, RequestValidationAppError
from app.joysafeter_shared.ids import CredentialId, TriggerId

_WEBHOOK_AUTH_METHODS = frozenset({"hmac", "bearer", "token"})


class WebhookAuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

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
        project_id: Optional[str],
        trigger_id: Optional[TriggerId] = None,
    ) -> str:
        cred_svc = CredentialService(self.db)
        credential = await cred_svc.get(webhook_auth_credential_id, project_id=project_id or "")
        context: dict[str, Any] = {"webhook_auth_credential_id": str(webhook_auth_credential_id)}
        if trigger_id is not None:
            context["trigger_id"] = str(trigger_id)
        if credential is None or credential.archived_at is not None:
            raise NotFoundError(
                code="TRIGGER_SECRET_NOT_FOUND",
                message=f"Credential not found: {webhook_auth_credential_id}",
                data=context,
                user_action="fix_input",
            )
        if credential.kind != CredentialKind.SERVICE.value:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_KIND_INVALID",
                message="Webhook triggers require a service Credential",
                data={**context, "kind": credential.kind},
                user_action="fix_input",
            )
        credential_data = cred_svc.get_credential_data(credential)
        if webhook_auth_field not in credential_data:
            raise RequestValidationAppError(
                code="TRIGGER_SECRET_KEY_NOT_FOUND",
                message=f"Credential field not found: {webhook_auth_field}",
                data={**context, "webhook_auth_field": webhook_auth_field},
                user_action="fix_input",
            )
        secret_value = credential_data[webhook_auth_field]
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
