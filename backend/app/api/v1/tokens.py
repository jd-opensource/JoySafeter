"""PlatformToken API routes.

Token management is session-auth only — PlatformToken cannot manage PlatformToken.
"""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import BadRequestException
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.platform_token import (
    TokenCreate,
    TokenCreateResponse,
    TokenSchema,
)
from app.services.platform_token_service import PlatformTokenService
from app.utils.string import is_valid_uuid

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
    return {
        "success": True,
        "data": {**TokenCreateResponse.model_validate(token_record).model_dump(), "token": raw_token},
    }


@router.get("")
async def list_tokens(
    resource_type: Optional[str] = Query(None),
    resource_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate resource_id is a valid UUID if provided
    parsed_resource_id = None
    if resource_id is not None:
        if not is_valid_uuid(resource_id):
            raise BadRequestException("Invalid resource_id: must be a valid UUID")
        parsed_resource_id = uuid.UUID(resource_id)

    service = PlatformTokenService(db)
    tokens = await service.list_tokens(
        user_id=current_user.id,
        resource_type=resource_type,
        resource_id=parsed_resource_id,
    )
    return {
        "success": True,
        "data": [TokenSchema.model_validate(t) for t in tokens],
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
