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
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.secret_service import SecretService

router = APIRouter(tags=["conductor-secrets"])


@router.post("", status_code=201)
async def create_secret(
    req: CreateSecretRequest, db: AsyncSession = Depends(get_db)
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.create_secret(req)
    return SecretResponse.model_validate(secret)


@router.get("")
async def list_secrets(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[SecretListItem]:
    svc = SecretService(db)
    secrets, has_more = await svc.list_secrets(limit, after_id)
    data = [SecretListItem.model_validate(s) for s in secrets]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{secret_id}")
async def get_secret(
    secret_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> SecretResponse:
    svc = SecretService(db)
    secret = await svc.get_secret(secret_id)
    if not secret:
        raise HTTPException(404, "Secret not found")
    return SecretResponse.model_validate(secret)


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
    return SecretResponse.model_validate(secret)


@router.delete("/{secret_id}", status_code=204)
async def delete_secret(
    secret_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    svc = SecretService(db)
    ok = await svc.delete_secret(secret_id)
    if not ok:
        raise HTTPException(404, "Secret not found")
