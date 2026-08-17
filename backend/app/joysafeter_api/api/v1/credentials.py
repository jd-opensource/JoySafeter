"""Id-based ``/credentials`` REST routes (P0 refactor, Task 8).

Replaces the old name-based ``/secrets`` API. Every route is backed by the
unified ``CredentialService``; reads are masked (a project reader can never
recover raw secret material — ``CredentialService.get_masked`` applies the
default-deny display-safe whitelist), writes require ``require_joysafeter_write``
and emit an audit event whose details never contain secret values (name / kind /
provider / protocol / keys only). The ``POST /credentials/test`` connectivity
adapter is ported verbatim from ``secrets.py``.
"""

from __future__ import annotations

import json
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_domain.llm.anthropic_auth import normalize_anthropic_auth
from app.joysafeter_domain.llm.catalog import LlmCatalogError, get_llm_catalog
from app.joysafeter_domain.llm.compatibility import (
    LlmCompatibilityError,
    compatible_engine_ids,
    resolve_credential_profile,
    validate_credential_data,
    validate_provider_protocol,
)
from app.joysafeter_domain.models.joysafeter_credential import JoySafeterCredential
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CreateCredentialRequest,
    CredentialKind,
    CredentialResponse,
    CredentialTestResponse,
    TestCredentialRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import CredentialId
from app.joysafeter_shared.llm.base_url import LLMBaseUrlError, validate_llm_base_url

router = APIRouter(tags=["joysafeter-credentials"])

CREDENTIAL_TEST_TIMEOUT_SECONDS = 20.0
CREDENTIAL_TEST_ERROR_DETAIL_LIMIT = 2000
CREDENTIAL_TEST_MAX_OUTPUT_TOKENS = 32


# --- response shaping (always masked) -------------------------------------------


def _catalog_identity(cred: JoySafeterCredential) -> tuple[str | None, list[str]]:
    """Resolve (model_key, compatible_engine_ids) for a model credential.

    Non-model credentials (and model credentials whose provider/protocol are no
    longer in the catalog) resolve to ``(None, [])``.
    """
    profile = resolve_credential_profile(cred)
    if profile is None or cred.provider is None or cred.protocol is None:
        return None, []
    return profile.model_key, compatible_engine_ids(cred.provider, cred.protocol)


def _credential_response(cred: JoySafeterCredential, svc: CredentialService) -> CredentialResponse:
    model_key, engine_ids = _catalog_identity(cred)
    masked = svc.get_masked(cred)
    model = (masked.get(model_key) or None) if model_key else None
    return CredentialResponse(
        id=cred.id,
        kind=CredentialKind(cred.kind),
        name=cred.name,
        data=masked,
        provider=cred.provider,
        protocol=cred.protocol,
        model=model,
        compatible_engine_ids=engine_ids,
        is_default=cred.is_default,
        mcp_server_url=cred.mcp_server_url,
        group_id=cred.group_id,
        archived_at=cred.archived_at,
        created_at=cred.created_at,
        updated_at=cred.updated_at,
    )


def _validate_list_filters(provider: str | None, protocol: str | None) -> None:
    """Reject unknown provider/protocol list filters against the LLM catalog.

    Mirrors the old ``/secrets`` list guard so a bad filter surfaces a semantic
    ``LLM_PROVIDER_UNKNOWN`` / ``LLM_PROTOCOL_UNKNOWN`` instead of silently
    returning an empty page.
    """
    catalog = get_llm_catalog()
    if provider is not None:
        try:
            catalog.provider(provider)
        except LlmCatalogError as exc:
            raise LlmCompatibilityError(
                code="LLM_PROVIDER_UNKNOWN",
                message=f"Unknown LLM provider: {provider}",
                data={"provider": provider},
                user_action="fix_input",
            ) from exc
    if protocol is not None:
        try:
            catalog.protocol(protocol)
        except LlmCatalogError as exc:
            raise LlmCompatibilityError(
                code="LLM_PROTOCOL_UNKNOWN",
                message=f"Unknown LLM protocol: {protocol}",
                data={"protocol": protocol},
                user_action="fix_input",
            ) from exc
    if provider is not None and protocol is not None:
        validate_provider_protocol(provider, protocol)


def _audit_details(cred: JoySafeterCredential) -> dict:
    """Non-sensitive audit details: name/kind/provider/protocol/keys only.

    Never includes any ``data`` value (masked or otherwise) — just the set of
    field names present, so the audit log records what changed without leaking
    secret material.
    """
    return {
        "name": cred.name,
        "kind": cred.kind,
        "provider": cred.provider,
        "protocol": cred.protocol,
        "keys": sorted((cred.data or {}).keys()),
    }


# --- test-connection helpers (ported verbatim from secrets.py) ------------------


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
                code="CREDENTIAL_TEST_BASE_URL_NOT_ALLOWED",
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
            code="CREDENTIAL_TEST_BASE_URL_INVALID",
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
    return text[:CREDENTIAL_TEST_ERROR_DETAIL_LIMIT] if text else None


def _apply_anthropic_auth(provider: str | None, data: dict[str, str], auth_scheme: str) -> dict[str, str]:
    if provider != "anthropic":
        return data
    return normalize_anthropic_auth(data, auth_scheme)


async def _test_credential_connectivity(req: TestCredentialRequest) -> CredentialTestResponse:
    data = {str(k): str(v) for k, v in (req.data or {}).items()}
    provider = req.provider
    protocol = req.protocol
    data = _apply_anthropic_auth(provider, data, req.auth_scheme)
    binding = validate_provider_protocol(provider, protocol)
    validate_credential_data(provider, protocol, data)
    profile = get_llm_catalog().credential_profile(binding.credential_profile_id)
    base_url_key = profile.base_url_key or "BASE_URL"
    base_url_value = data.get(base_url_key) or binding.default_base_url
    if not base_url_value:
        raise InvalidRequestError(
            code="CREDENTIAL_TEST_BASE_URL_REQUIRED",
            message=f"{base_url_key} is required for this provider",
            data={"provider": provider, "protocol": protocol, "key": base_url_key},
            user_action="fix_input",
        )
    base_url = _validate_llm_base_url(base_url_value, key=base_url_key, provider=provider)
    model = data.get(profile.model_key, "") if profile.model_key else ""

    if profile.id == "anthropic_standard" and protocol == "anthropic_messages":
        api_key = data.get("ANTHROPIC_API_KEY") or ""
        auth_token = data.get("ANTHROPIC_AUTH_TOKEN") or ""
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
            "model": model or "claude-3-5-haiku-latest",
            "max_tokens": CREDENTIAL_TEST_MAX_OUTPUT_TOKENS,
            "messages": [{"role": "user", "content": "ping"}],
        }
    elif profile.id == "openai_bearer" and protocol in {"openai_responses", "chat_completions"}:
        api_key = data.get("OPENAI_API_KEY") or ""
        headers = {
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        }
        if protocol == "chat_completions":
            endpoint = _url_join(base_url, "/chat/completions")
            body = {
                "model": model or "gpt-4.1-mini",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": CREDENTIAL_TEST_MAX_OUTPUT_TOKENS,
                "stream": False,
            }
        else:
            endpoint = _url_join(base_url, "/responses")
            body = {
                "model": model or "gpt-4.1-mini",
                "input": "ping",
                "max_output_tokens": CREDENTIAL_TEST_MAX_OUTPUT_TOKENS,
                "stream": False,
            }
    else:
        raise InvalidRequestError(
            code="CREDENTIAL_TEST_CREDENTIAL_PROFILE_UNSUPPORTED",
            message="The selected credential profile has no connectivity adapter.",
            data={
                "provider": provider,
                "protocol": protocol,
                "credential_profile_id": profile.id,
            },
            user_action="fix_input",
        )

    try:
        async with httpx.AsyncClient(
            timeout=CREDENTIAL_TEST_TIMEOUT_SECONDS, follow_redirects=False
        ) as client:
            response = await client.post(endpoint, headers=headers, json=body)
    except httpx.HTTPError as exc:
        return CredentialTestResponse(
            ok=False,
            provider=provider,
            protocol=protocol,
            endpoint=endpoint,
            message=f"Failed to connect to upstream API ({exc.__class__.__name__}).",
            error_detail=str(exc)[:CREDENTIAL_TEST_ERROR_DETAIL_LIMIT],
        )

    if 200 <= response.status_code < 300:
        return CredentialTestResponse(
            ok=True,
            provider=provider,
            protocol=protocol,
            endpoint=endpoint,
            status=response.status_code,
            message="Connection test succeeded.",
        )

    return CredentialTestResponse(
        ok=False,
        provider=provider,
        protocol=protocol,
        endpoint=endpoint,
        status=response.status_code,
        message=_extract_upstream_error(response),
        error_detail=_extract_upstream_error_detail(response),
    )


# --- routes ----------------------------------------------------------------------


@router.post("", status_code=201)
async def create_credential(
    req: CreateCredentialRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialResponse:
    svc = CredentialService(db, auto_commit=False)
    req.data = _apply_anthropic_auth(req.provider, req.data, req.auth_scheme)
    cred = await svc.create(req, project_id=auth_ctx.project_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="credential.created",
        target_type="credential",
        target_id=str(cred.id),
        details=_audit_details(cred),
        commit=False,
        best_effort=False,
    )
    await db.commit()
    await svc.nudge_pending_network_policy_refreshes()
    return _credential_response(cred, svc)


@router.post("/test")
async def test_credential(
    req: TestCredentialRequest,
    _auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialTestResponse:
    return await _test_credential_connectivity(req)


@router.get("")
async def list_credentials(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[CredentialId] = Query(None),
    include_archived: Optional[bool] = Query(None),
    kind: Optional[CredentialKind] = Query(None),
    name: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    protocol: Optional[str] = Query(None),
    compatible_engine: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
):
    svc = CredentialService(db)
    _validate_list_filters(provider, protocol)
    creds, has_more = await svc.list(
        project_id=auth_ctx.project_id,
        kind=kind,
        name=name,
        provider=provider,
        protocol=protocol,
        compatible_engine=compatible_engine,
        include_archived=include_archived,
        limit=limit,
        after_id=after_id,
    )
    items = [_credential_response(c, svc) for c in creds]
    return {
        "data": [item.model_dump(mode="json") for item in items],
        "has_more": has_more,
        "first_id": str(creds[0].id) if creds else None,
        "last_id": str(creds[-1].id) if creds else None,
    }


@router.get("/{credential_id}")
async def get_credential(
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> CredentialResponse:
    svc = CredentialService(db)
    cred = await svc._get_or_raise(credential_id, project_id=auth_ctx.project_id)
    return _credential_response(cred, svc)


@router.patch("/{credential_id}")
async def update_credential(
    req: UpdateCredentialRequest,
    request: Request,
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialResponse:
    svc = CredentialService(db, auto_commit=False)
    if req.data is not None:
        existing = await svc._get_or_raise(credential_id, project_id=auth_ctx.project_id)
        req.data = _apply_anthropic_auth(getattr(existing, "provider", None), req.data, req.auth_scheme)
    cred = await svc.update(credential_id, req, project_id=auth_ctx.project_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="credential.updated",
        target_type="credential",
        target_id=str(cred.id),
        details=_audit_details(cred),
        commit=False,
        best_effort=False,
    )
    await db.commit()
    await svc.nudge_pending_network_policy_refreshes()
    return _credential_response(cred, svc)


@router.delete("/{credential_id}", status_code=204)
async def delete_credential(
    request: Request,
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> None:
    svc = CredentialService(db, auto_commit=False)
    # Lifecycle soft_delete raises CREDENTIAL_IN_USE (409) when still referenced.
    cred = await svc.soft_delete(credential_id, project_id=auth_ctx.project_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="credential.deleted",
        target_type="credential",
        target_id=str(credential_id),
        details=_audit_details(cred),
        commit=False,
        best_effort=False,
    )
    await db.commit()
    await svc.nudge_pending_network_policy_refreshes()


@router.post("/{credential_id}/default")
async def set_default_credential(
    request: Request,
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialResponse:
    svc = CredentialService(db, auto_commit=False)
    cred = await svc.set_default(credential_id, project_id=auth_ctx.project_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="credential.default_set",
        target_type="credential",
        target_id=str(cred.id),
        details=_audit_details(cred),
        commit=False,
        best_effort=False,
    )
    await db.commit()
    await svc.nudge_pending_network_policy_refreshes()
    return _credential_response(cred, svc)


@router.post("/{credential_id}/archive")
async def archive_credential(
    request: Request,
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialResponse:
    svc = CredentialService(db, auto_commit=False)
    # Lifecycle archive raises CREDENTIAL_IN_USE (409) when still referenced.
    cred = await svc.archive(credential_id, project_id=auth_ctx.project_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="credential.archived",
        target_type="credential",
        target_id=str(cred.id),
        details=_audit_details(cred),
        commit=False,
        best_effort=False,
    )
    await db.commit()
    await svc.nudge_pending_network_policy_refreshes()
    return _credential_response(cred, svc)


@router.post("/{credential_id}/restore")
async def restore_credential(
    request: Request,
    credential_id: CredentialId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> CredentialResponse:
    svc = CredentialService(db, auto_commit=False)
    cred = await svc.restore(credential_id, project_id=auth_ctx.project_id)
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="credential.restored",
        target_type="credential",
        target_id=str(cred.id),
        details=_audit_details(cred),
        commit=False,
        best_effort=False,
    )
    await db.commit()
    await svc.nudge_pending_network_policy_refreshes()
    return _credential_response(cred, svc)
