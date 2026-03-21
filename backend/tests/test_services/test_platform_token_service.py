"""Unit tests for PlatformTokenService."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    return db


class TestPlatformTokenServiceCreate:
    """Test token creation logic."""

    @pytest.mark.asyncio
    async def test_create_returns_raw_token_starting_with_sk(self):
        """Created token should start with 'sk_' prefix."""
        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user = AsyncMock(return_value=0)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            record, raw_token = await service.create_token(
                user_id="user-1",
                name="test",
                scopes=["skills:read"],
            )
            assert raw_token.startswith("sk_")
            assert len(raw_token) > 12

    @pytest.mark.asyncio
    async def test_create_rejects_when_limit_exceeded(self):
        """Should raise BadRequestException when user has 50 active tokens."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user = AsyncMock(return_value=50)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(BadRequestException, match="50"):
                await service.create_token(
                    user_id="user-1",
                    name="test",
                    scopes=["skills:read"],
                )


class TestPlatformTokenServiceRevoke:
    """Test token revocation logic."""

    @pytest.mark.asyncio
    async def test_revoke_sets_inactive(self):
        """Revoke should set is_active to False."""
        db = _mock_db()
        token = MagicMock()
        token.id = uuid.uuid4()
        token.user_id = "user-1"
        token.is_active = True
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.get = AsyncMock(return_value=token)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            await service.revoke_token(token_id=token.id, user_id="user-1")
            assert token.is_active is False

    @pytest.mark.asyncio
    async def test_revoke_wrong_user_denied(self):
        """Should raise ForbiddenException when revoking another user's token."""
        from app.common.exceptions import ForbiddenException

        db = _mock_db()
        token = MagicMock()
        token.id = uuid.uuid4()
        token.user_id = "user-1"
        token.is_active = True
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.get = AsyncMock(return_value=token)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(ForbiddenException):
                await service.revoke_token(token_id=token.id, user_id="user-2")
