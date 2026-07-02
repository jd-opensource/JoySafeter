import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import audit_joysafeter_event
from app.joysafeter_api.api.v1.id_helpers import parse_secret_id
from app.joysafeter_api.services import SecretService
from app.joysafeter_domain.schemas.joysafeter_secret import (
    CreateSecretRequest,
    SecretListItem,
    SecretResponse,
    UpdateSecretRequest,
)
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-secrets"])


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
        raise HTTPException(400, str(exc)) from exc
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
        "first_id": str(items[0].id) if items else None,
        "last_id": str(items[-1].id) if items else None,
    }


@router.get("/{secret_id}")
async def get_secret(
    secret_id: uuid.UUID = Depends(parse_secret_id),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.get_secret(secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")
    if secret.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Secret not found")
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
    secret = await svc.get_secret(secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")
    if secret.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Secret not found")
    try:
        secret = await svc.update_secret(secret_id, req)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if secret is None:
        raise HTTPException(404, "Secret not found")
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
        raise HTTPException(404, "Secret not found")
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
    secret = await svc.get_secret(secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")
    if secret.project_id != auth_ctx.project_id:
        raise HTTPException(404, "Secret not found")

    if not force:
        agent_name = await svc.secret_is_referenced_by_agent(secret.name, project_id=auth_ctx.project_id)
        if agent_name:
            raise HTTPException(
                409,
                f"Secret is referenced by agent '{agent_name}'. Use ?force=true to force delete.",
            )

    if force:
        await svc.hard_delete_secret(secret_id)
    else:
        ok = await svc.delete_secret(secret_id)
        if not ok:
            raise HTTPException(404, "Secret not found")
    await audit_joysafeter_event(
        db,
        request,
        auth_ctx,
        event_type="secret.deleted",
        target_type="secret",
        target_id=str(secret_id),
        details={"name": secret.name, "force": force},
    )
