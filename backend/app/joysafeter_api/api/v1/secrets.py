import json
import uuid
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_api.api.v1.id_helpers import parse_secret_id
from app.joysafeter_domain.schemas.joysafeter_secret import (
    CreateSecretRequest,
    SecretListItem,
    SecretResponse,
    SecretTestResponse,
    TestSecretRequest,
    UpdateSecretRequest,
)
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_shared.common.app_errors import (
    AppError,
    InvalidRequestError,
    NotFoundError,
    ResourceConflictError,
    ServiceUnavailableError,
)
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.llm.base_url import LLMBaseUrlError, validate_llm_base_url
from app.joysafeter_shared.utils.id_utils import format_task_id

router = APIRouter(tags=["joysafeter-secrets"])

SECRET_TEST_TIMEOUT_SECONDS = 20.0
SECRET_TEST_ERROR_DETAIL_LIMIT = 2000
SECRET_TEST_MAX_OUTPUT_TOKENS = 32
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _secret_not_found_error(secret_id: uuid.UUID) -> AppError:
    return NotFoundError(
        code="SECRET_NOT_FOUND",
        message="Secret not found",
        data={"secret_id": str(secret_id)},
        user_action="refresh",
    )


def _secret_active_task_error(
    *,
    secret_id: uuid.UUID,
    secret_name: str,
    task_id: uuid.UUID | str,
    source: str,
    operation: str,
) -> AppError:
    return ResourceConflictError(
        code="SECRET_ACTIVE_TASK_DEPENDENCY",
        message=f"Secret is required by active task '{task_id}' via {source}. Stop or wait for the task before {operation}.",
        data={
            "secret_id": str(secret_id),
            "secret_name": secret_name,
            "task_id": format_task_id(task_id),
            "source": source,
            "operation": operation,
        },
        retryable=True,
        user_action="retry",
    )


def _secret_reference_error(
    *,
    secret_id: uuid.UUID,
    secret_name: str,
    code: str,
    message: str,
    reference_key: str,
    reference_value: str,
) -> AppError:
    return ResourceConflictError(
        code=code,
        message=message,
        data={
            "secret_id": str(secret_id),
            "secret_name": secret_name,
            reference_key: reference_value,
        },
    )


def _secret_value_error(*, exc: ValueError, operation: str) -> AppError:
    message = str(exc)
    data = {"operation": operation}
    if "JOYSAFETER_VAULT_ENCRYPTION_KEY" in message:
        return ServiceUnavailableError(
            code="SECRET_VAULT_CONFIGURATION_REQUIRED",
            message="Managed secrets require JOYSAFETER_VAULT_ENCRYPTION_KEY to be configured.",
            data=data,
            user_action="configure",
        )
    return InvalidRequestError(
        code="SECRET_VALIDATION_FAILED",
        message=message,
        data=data,
        user_action="fix_input",
    )


def _url_join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _append_anthropic_messages_path(base_url: str) -> str:
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        return _url_join(base_url, "/messages")
    return _url_join(base_url, "/v1/messages")


def _validate_llm_base_url(base_url: str, *, key: str, provider: str) -> str:
    try:
        return validate_llm_base_url(base_url, key=key)
    except LLMBaseUrlError as exc:
        if exc.reason == "not_allowed":
            raise InvalidRequestError(
                code="SECRET_TEST_BASE_URL_NOT_ALLOWED",
                message=f"{key} host is not allowlisted.",
                data={
                    "provider": provider,
                    "key": key,
                    "base_url": base_url,
                    "host": exc.host,
                },
                user_action="fix_input",
            ) from None
        raise InvalidRequestError(
            code="SECRET_TEST_BASE_URL_INVALID",
            message=f"Invalid {key}",
            data={"provider": provider, "key": key, "base_url": base_url},
            user_action="fix_input",
        ) from None


def _extract_upstream_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and str(error.get("message") or "").strip():
                return str(error["message"]).strip()
            if str(payload.get("message") or "").strip():
                return str(payload["message"]).strip()
    except ValueError:
        pass
    text = response.text.strip()
    return text[:500] if text else f"HTTP {response.status_code}"


def _extract_upstream_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
    else:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text[:SECRET_TEST_ERROR_DETAIL_LIMIT] if text else None


def _provider_family(provider: str, protocol: str) -> str:
    provider = provider.lower()
    protocol = protocol.lower()
    if protocol == "anthropic_messages" or provider in {"claude", "anthropic"}:
        return "anthropic"
    if protocol in {"openai_responses", "chat_completions"} or provider in {"codex", "openai"}:
        return "openai"
    return "unsupported"


async def _test_secret_connectivity(req: TestSecretRequest) -> SecretTestResponse:
    data = SecretService.apply_provider_aliases({str(k): str(v) for k, v in (req.data or {}).items()})
    provider = req.provider or "custom"
    protocol = req.protocol or "custom"
    family = _provider_family(provider, protocol)

    if family == "anthropic":
        api_key = data.get("ANTHROPIC_API_KEY") or ""
        auth_token = data.get("ANTHROPIC_AUTH_TOKEN") or ""
        credential = auth_token or api_key
        if not credential:
            raise InvalidRequestError(
                code="SECRET_TEST_MISSING_KEY",
                message="Secret missing ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN.",
                data={"provider": provider, "required_key": "ANTHROPIC_API_KEY"},
                user_action="fix_input",
            )

        base_url = _validate_llm_base_url(
            data.get("ANTHROPIC_BASE_URL") or ANTHROPIC_DEFAULT_BASE_URL,
            key="ANTHROPIC_BASE_URL",
            provider=provider,
        )
        endpoint = _append_anthropic_messages_path(base_url)
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if auth_token:
            headers["authorization"] = f"Bearer {auth_token}"
        else:
            headers["x-api-key"] = api_key
        body = {
            "model": data.get("ANTHROPIC_MODEL") or data.get("MODEL") or "claude-3-5-haiku-latest",
            "max_tokens": SECRET_TEST_MAX_OUTPUT_TOKENS,
            "messages": [{"role": "user", "content": "ping"}],
        }
    elif family == "openai":
        api_key = data.get("OPENAI_API_KEY") or ""
        if not api_key:
            raise InvalidRequestError(
                code="SECRET_TEST_MISSING_KEY",
                message="Secret missing OPENAI_API_KEY.",
                data={"provider": provider, "required_key": "OPENAI_API_KEY"},
                user_action="fix_input",
            )

        base_url = _validate_llm_base_url(
            data.get("OPENAI_BASE_URL") or OPENAI_DEFAULT_BASE_URL,
            key="OPENAI_BASE_URL",
            provider=provider,
        )
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        if protocol == "chat_completions":
            endpoint = _url_join(base_url, "/chat/completions")
            body = {
                "model": data.get("OPENAI_MODEL") or data.get("MODEL") or "gpt-4.1-mini",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": SECRET_TEST_MAX_OUTPUT_TOKENS,
                "stream": False,
            }
        else:
            endpoint = _url_join(base_url, "/responses")
            body = {
                "model": data.get("OPENAI_MODEL") or data.get("MODEL") or "gpt-4.1-mini",
                "input": "ping",
                "max_output_tokens": SECRET_TEST_MAX_OUTPUT_TOKENS,
                "stream": False,
            }
    else:
        raise InvalidRequestError(
            code="SECRET_TEST_PROVIDER_UNSUPPORTED",
            message="Only Anthropic Messages, OpenAI Responses, and Chat Completions secrets can be tested.",
            data={"provider": provider, "protocol": protocol},
            user_action="fix_input",
        )

    try:
        async with httpx.AsyncClient(timeout=SECRET_TEST_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = await client.post(endpoint, headers=headers, json=body)
    except httpx.HTTPError as exc:
        return SecretTestResponse(
            ok=False,
            provider=provider,
            protocol=protocol,
            endpoint=endpoint,
            message=f"Failed to connect to upstream API ({exc.__class__.__name__}).",
            error_detail=str(exc)[:SECRET_TEST_ERROR_DETAIL_LIMIT],
        )

    if 200 <= response.status_code < 300:
        return SecretTestResponse(
            ok=True,
            provider=provider,
            protocol=protocol,
            endpoint=endpoint,
            status=response.status_code,
            message="Connection test succeeded.",
        )

    return SecretTestResponse(
        ok=False,
        provider=provider,
        protocol=protocol,
        endpoint=endpoint,
        status=response.status_code,
        message=_extract_upstream_error(response),
        error_detail=_extract_upstream_error_detail(response),
    )


@router.post("", status_code=201)
async def create_secret(
    req: CreateSecretRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SecretResponse:
    svc = SecretService(db)
    try:
        secret = await svc.create_secret(req, project_id=auth_ctx.project_id)
    except ValueError as exc:
        raise _secret_value_error(exc=exc, operation="create") from exc
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="secret.created",
        target_type="secret",
        target_id=str(secret.id),
        details={
            "name": secret.name,
            "provider": secret.provider,
            "protocol": secret.protocol,
            "keys": sorted((secret.data or {}).keys()),
        },
    )
    return SecretResponse(
        id=f"secret_{secret.id}",
        name=secret.name,
        provider=secret.provider,
        protocol=secret.protocol,
        is_default=secret.is_default,
        secret_data=svc.get_masked_secret_data(secret),
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.post("/test")
async def test_secret(
    req: TestSecretRequest,
    _auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SecretTestResponse:
    return await _test_secret_connectivity(req)


@router.get("")
async def list_secrets(
    limit: int = Query(10, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = SecretService(db)
    secrets, has_more = await svc.list_secrets(limit, after_id, project_id=auth_ctx.project_id)
    items = [
        SecretListItem(
            id=f"secret_{s.id}",
            name=s.name,
            provider=s.provider,
            protocol=s.protocol,
            is_default=s.is_default,
            keys=list(s.data.keys()) if s.data else [],
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in secrets
    ]
    return {
        "data": [item.model_dump(mode="json") for item in items],
        "has_more": has_more,
        "first_id": str(secrets[0].id) if secrets else None,
        "last_id": str(secrets[-1].id) if secrets else None,
    }


@router.get("/{secret_id}")
async def get_secret(
    secret_id: uuid.UUID = Depends(parse_secret_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.get_secret(secret_id, project_id=auth_ctx.project_id)
    if not secret:
        raise _secret_not_found_error(secret_id)
    return SecretResponse(
        id=f"secret_{secret.id}",
        name=secret.name,
        provider=secret.provider,
        protocol=secret.protocol,
        is_default=secret.is_default,
        secret_data=svc.get_masked_secret_data(secret),
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.put("/{secret_id}")
async def update_secret(
    req: UpdateSecretRequest,
    request: Request,
    secret_id: uuid.UUID = Depends(parse_secret_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.get_secret(secret_id, project_id=auth_ctx.project_id)
    if not secret:
        raise _secret_not_found_error(secret_id)
    active_dependency = await svc.active_task_secret_dependency(secret.name, project_id=auth_ctx.project_id)
    if active_dependency:
        task_id, source = active_dependency
        raise _secret_active_task_error(
            secret_id=secret_id,
            secret_name=secret.name,
            task_id=task_id,
            source=source,
            operation="updating",
        )
    try:
        secret = await svc.update_secret(secret_id, req, project_id=auth_ctx.project_id)
    except ValueError as exc:
        raise _secret_value_error(exc=exc, operation="update") from exc
    if secret is None:
        raise _secret_not_found_error(secret_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="secret.updated",
        target_type="secret",
        target_id=str(secret.id),
        details={
            "name": secret.name,
            "provider": secret.provider,
            "protocol": secret.protocol,
            "keys": sorted((secret.data or {}).keys()),
        },
    )
    return SecretResponse(
        id=f"secret_{secret.id}",
        name=secret.name,
        provider=secret.provider,
        protocol=secret.protocol,
        is_default=secret.is_default,
        secret_data=svc.get_masked_secret_data(secret),
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.post("/{secret_id}/default")
async def set_default_secret(
    request: Request,
    secret_id: uuid.UUID = Depends(parse_secret_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.set_default_secret(secret_id, project_id=auth_ctx.project_id)
    if not secret:
        raise _secret_not_found_error(secret_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="secret.default_set",
        target_type="secret",
        target_id=str(secret.id),
        details={"name": secret.name, "provider": secret.provider, "protocol": secret.protocol},
    )
    return SecretResponse(
        id=f"secret_{secret.id}",
        name=secret.name,
        provider=secret.provider,
        protocol=secret.protocol,
        is_default=secret.is_default,
        secret_data={},
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.delete("/{secret_id}", status_code=204)
async def delete_secret(
    request: Request,
    secret_id: uuid.UUID = Depends(parse_secret_id),
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = SecretService(db)
    secret = await svc.get_secret(secret_id, project_id=auth_ctx.project_id)
    if not secret:
        raise _secret_not_found_error(secret_id)

    active_dependency = await svc.active_task_secret_dependency(secret.name, project_id=auth_ctx.project_id)
    if active_dependency:
        task_id, source = active_dependency
        raise _secret_active_task_error(
            secret_id=secret_id,
            secret_name=secret.name,
            task_id=task_id,
            source=source,
            operation="deleting",
        )

    if not force:
        agent_name = await svc.secret_is_referenced_by_agent(secret.name, project_id=auth_ctx.project_id)
        if agent_name:
            raise _secret_reference_error(
                secret_id=secret_id,
                secret_name=secret.name,
                code="SECRET_AGENT_REFERENCE",
                message=f"Secret is referenced by agent '{agent_name}'. Use ?force=true to force delete.",
                reference_key="agent_name",
                reference_value=agent_name,
            )
        environment_name = await svc.secret_is_referenced_by_environment(secret.name, project_id=auth_ctx.project_id)
        if environment_name:
            raise _secret_reference_error(
                secret_id=secret_id,
                secret_name=secret.name,
                code="SECRET_ENVIRONMENT_REFERENCE",
                message=f"Secret is referenced by environment '{environment_name}'. Use ?force=true to force delete.",
                reference_key="environment_name",
                reference_value=environment_name,
            )

    if force:
        ok = await svc.hard_delete_secret(secret_id, project_id=auth_ctx.project_id)
        if not ok:
            raise _secret_not_found_error(secret_id)
    else:
        ok = await svc.delete_secret(secret_id, project_id=auth_ctx.project_id)
        if not ok:
            raise _secret_not_found_error(secret_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="secret.deleted",
        target_type="secret",
        target_id=str(secret_id),
        details={"name": secret.name, "force": force},
    )
