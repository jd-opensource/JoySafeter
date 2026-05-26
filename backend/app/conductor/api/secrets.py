import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.secret import (
    CreateSecretRequest,
    SecretListItem,
    SecretResponse,
    UpdateSecretRequest,
)
from app.conductor.services.secret_service import SecretService

router = APIRouter(tags=["conductor-secrets"])


@router.post("", status_code=201)
async def create_secret(
    req: CreateSecretRequest, db: AsyncSession = Depends(get_db)
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.create_secret(req)
    return SecretResponse(
        id=secret.id,
        name=secret.name,
        data=secret.data or {},
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.get("")
async def list_secrets(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[SecretListItem]:
    svc = SecretService(db)
    secrets, has_more = await svc.list_secrets(limit, after_id)
    return [
        SecretListItem(
            id=s.id,
            name=s.name,
            keys=list(s.data.keys()) if s.data else [],
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in secrets
    ]


@router.get("/{secret_id}")
async def get_secret(
    secret_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.get_secret(secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")
    return SecretResponse(
        id=secret.id,
        name=secret.name,
        data=secret.data or {},
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.put("/{secret_id}")
async def update_secret(
    secret_id: uuid.UUID,
    req: UpdateSecretRequest,
    db: AsyncSession = Depends(get_db),
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.update_secret(secret_id, req)
    if not secret:
        raise HTTPException(404, "Secret not found")
    return SecretResponse(
        id=secret.id,
        name=secret.name,
        data=secret.data or {},
        created_at=secret.created_at,
        updated_at=secret.updated_at,
    )


@router.delete("/{secret_id}", status_code=204)
async def delete_secret(
    secret_id: uuid.UUID,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = SecretService(db)
    secret = await svc.get_secret(secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")

    if not force:
        agent_name = await svc.secret_is_referenced_by_agent(secret.name)
        if agent_name:
            raise HTTPException(
                409,
                f"Secret is referenced by agent '{agent_name}'. "
                "Use ?force=true to force delete.",
            )

    if force:
        await svc.hard_delete_secret(secret_id)
    else:
        ok = await svc.delete_secret(secret_id)
        if not ok:
            raise HTTPException(404, "Secret not found")
