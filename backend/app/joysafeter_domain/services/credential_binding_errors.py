from __future__ import annotations

from app.joysafeter_domain.credentials.policies import CredentialPolicyError, CredentialPolicyErrorCode
from app.joysafeter_domain.llm.model_inference_policy import (
    ModelInferencePolicyError,
    ModelInferencePolicyErrorCode,
)
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.ids import CredentialId


def raise_public_credential_error(
    exc: Exception,
    *,
    credential_id: CredentialId | None = None,
    data: dict[str, object] | None = None,
    constructor_error: str = "corrupt",
    not_found_user_action: str | None = None,
) -> None:
    payload = dict(data or {})
    if credential_id is not None:
        payload.setdefault("credential_id", str(credential_id))
    if isinstance(exc, ModelInferencePolicyError):
        if exc.code is ModelInferencePolicyErrorCode.ENGINE_DISABLED:
            raise InvalidRequestError(
                code="LLM_ENGINE_DISABLED",
                message=f"LLM engine is disabled: {exc.engine_kind.value}",
                data={"engine_kind": exc.engine_kind.value},
                user_action="fix_input",
            ) from exc
    if isinstance(exc, LookupError):
        raise NotFoundError(
            code="CREDENTIAL_NOT_FOUND",
            message="Credential not found",
            data=payload,
            user_action=not_found_user_action,
        ) from exc
    if isinstance(exc, CredentialPolicyError):
        if exc.code in {CredentialPolicyErrorCode.DELETED, CredentialPolicyErrorCode.PROJECT_MISMATCH}:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data=payload,
                user_action=not_found_user_action,
            ) from exc
        if exc.code is CredentialPolicyErrorCode.ARCHIVED:
            raise ResourceConflictError(
                code="CREDENTIAL_STATE_INVALID",
                message="Credential state is invalid for this operation",
                data=payload,
                user_action="refresh",
            ) from exc
        if exc.code in {
            CredentialPolicyErrorCode.KIND_MISMATCH,
            CredentialPolicyErrorCode.CATALOG_MISMATCH,
            CredentialPolicyErrorCode.UNSUPPORTED_SCHEME,
        }:
            raise InvalidRequestError(
                code="CREDENTIAL_KIND_INVALID",
                message="Credential kind is invalid for this operation",
                data=payload,
                user_action="fix_input",
            ) from exc
        if exc.code is CredentialPolicyErrorCode.FIELD_MISSING:
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_MISSING",
                message="A required credential field is missing",
                data=payload,
                user_action="fix_input",
            ) from exc
        if exc.code is CredentialPolicyErrorCode.URL_CONFLICT:
            raise ResourceConflictError(
                code="CREDENTIAL_GROUP_URL_CONFLICT",
                message="Credential group URL conflict",
                data=payload,
                user_action="fix_input",
            ) from exc
    if isinstance(exc, (TypeError, ValueError)):
        if constructor_error == "field_missing":
            raise InvalidRequestError(
                code="CREDENTIAL_FIELD_MISSING",
                message="A required credential field is missing",
                data=payload,
                user_action="fix_input",
            ) from exc
        if constructor_error == "url_conflict":
            raise ResourceConflictError(
                code="CREDENTIAL_GROUP_URL_CONFLICT",
                message="Credential group URL conflict",
                data=payload,
                user_action="fix_input",
            ) from exc
    raise InvalidRequestError(
        code="CREDENTIAL_CORRUPT",
        message="Credential record is corrupt",
        data=payload,
        user_action="refresh",
    ) from exc
