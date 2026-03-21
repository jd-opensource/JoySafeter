"""PlatformToken Service — create, list, revoke."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime
from typing import List, Optional, Tuple

from app.common.exceptions import BadRequestException, ForbiddenException, NotFoundException
from app.models.platform_token import PlatformToken
from app.repositories.platform_token import PlatformTokenRepository

from .base import BaseService

MAX_ACTIVE_TOKENS_PER_USER = 50
TOKEN_PREFIX = "sk_"


class PlatformTokenService(BaseService[PlatformToken]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = PlatformTokenRepository(db)

    async def create_token(
        self,
        user_id: str,
        name: str,
        scopes: List[str],
        resource_type: Optional[str] = None,
        resource_id: Optional[uuid.UUID] = None,
        expires_at: Optional[datetime] = None,
    ) -> Tuple[PlatformToken, str]:
        """Create a new token. Returns (token_record, plaintext_token)."""
        # Check limit
        active_count = await self.repo.count_active_by_user(user_id)
        if active_count >= MAX_ACTIVE_TOKENS_PER_USER:
            raise BadRequestException(f"Maximum of {MAX_ACTIVE_TOKENS_PER_USER} active tokens reached")

        # Generate token
        raw_secret = secrets.token_urlsafe(36)  # ~48 chars
        plaintext = f"{TOKEN_PREFIX}{raw_secret}"
        token_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        token_prefix = plaintext[:12]

        pt = PlatformToken(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            token_prefix=token_prefix,
            scopes=scopes,
            resource_type=resource_type,
            resource_id=resource_id,
            expires_at=expires_at,
            is_active=True,
        )
        self.db.add(pt)
        await self.db.commit()
        await self.db.refresh(pt)
        return pt, plaintext

    async def list_tokens(self, user_id: str) -> List[PlatformToken]:
        return await self.repo.list_by_user(user_id)

    async def revoke_token(
        self,
        token_id: uuid.UUID,
        user_id: str,
    ) -> None:
        pt = await self.repo.get(token_id)
        if not pt:
            raise NotFoundException("Token not found")
        if pt.user_id != user_id:
            raise ForbiddenException("You can only revoke your own tokens")
        pt.is_active = False
        await self.db.commit()
