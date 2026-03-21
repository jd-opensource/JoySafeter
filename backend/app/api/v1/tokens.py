"""PlatformToken API routes.

Token management is session-auth only — PlatformToken cannot manage PlatformToken.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.platform_token import (
    TokenCreate,
    TokenCreateResponse,
    TokenSchema,
)
from app.services.platform_token_service import PlatformTokenService

router = APIRouter(prefix="/v1/tokens", tags=["Tokens"])


@router.post("")
async def create_token(
    payload: TokenCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = PlatformTokenService(db)
    token_record, raw_token = await service.create_token(
        user_id=current_user.id,
        name=payload.name,
        scopes=payload.scopes,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        expires_at=payload.expires_at,
    )
    resp = TokenCreateResponse.model_validate(token_record)
    # Inject the raw token (not stored in DB)
    data = resp.model_dump()
    data["token"] = raw_token
    return {"success": True, "data": data}


@router.get("")
async def list_tokens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = PlatformTokenService(db)
    tokens = await service.list_tokens(user_id=current_user.id)
    return {
        "success": True,
        "data": [TokenSchema.model_validate(t).model_dump() for t in tokens],
    }


@router.delete("/{token_id}")
async def revoke_token(
    token_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = PlatformTokenService(db)
    await service.revoke_token(token_id=token_id, user_id=current_user.id)
    return {"success": True}
