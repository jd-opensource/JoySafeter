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

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_scope(self):
        """Should raise BadRequestException when passing invalid scope."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user = AsyncMock(return_value=0)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(BadRequestException, match="Invalid scopes"):
                await service.create_token(
                    user_id="user-1",
                    name="test",
                    scopes=["invalid:scope"],
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


class TestPlatformTokenServiceList:
    """Test token listing with resource filtering."""

    @pytest.mark.asyncio
    async def test_list_tokens_delegates_to_repo(self):
        """list_tokens should pass resource filters to repository."""
        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            mock_tokens = [MagicMock(), MagicMock()]
            MockRepo.return_value.list_by_user_and_resource = AsyncMock(return_value=mock_tokens)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            rid = uuid.uuid4()
            result = await service.list_tokens(
                user_id="user-1",
                resource_type="skill",
                resource_id=rid,
            )
            assert result == mock_tokens
            MockRepo.return_value.list_by_user_and_resource.assert_called_once_with("user-1", "skill", rid)

    @pytest.mark.asyncio
    async def test_list_tokens_no_filters(self):
        """list_tokens with no filters passes None values."""
        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.list_by_user_and_resource = AsyncMock(return_value=[])
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            result = await service.list_tokens(user_id="user-1")
            assert result == []
            MockRepo.return_value.list_by_user_and_resource.assert_called_once_with("user-1", None, None)


class TestPlatformTokenServiceRevokeByResource:
    """Test bulk revocation by resource."""

    @pytest.mark.asyncio
    async def test_revoke_by_resource_delegates_to_repo(self):
        """revoke_by_resource should delegate to repo.deactivate_by_resource."""
        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.deactivate_by_resource = AsyncMock(return_value=3)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            count = await service.revoke_by_resource("skill", "skill-123")
            assert count == 3
            MockRepo.return_value.deactivate_by_resource.assert_called_once_with("skill", "skill-123")


class TestPlatformTokenServiceValidation:
    """Test resource_type/resource_id pair and resource_type validation."""

    @pytest.mark.asyncio
    async def test_create_rejects_resource_type_without_resource_id(self):
        """Should reject when resource_type is set but resource_id is None."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user = AsyncMock(return_value=0)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(BadRequestException, match="must both be provided"):
                await service.create_token(
                    user_id="user-1",
                    name="test",
                    scopes=["skills:read"],
                    resource_type="skill",
                    resource_id=None,
                )

    @pytest.mark.asyncio
    async def test_create_rejects_resource_id_without_resource_type(self):
        """Should reject when resource_id is set but resource_type is None."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user = AsyncMock(return_value=0)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(BadRequestException, match="must both be provided"):
                await service.create_token(
                    user_id="user-1",
                    name="test",
                    scopes=["skills:read"],
                    resource_type=None,
                    resource_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_create_rejects_invalid_resource_type(self):
        """Should reject unknown resource_type."""
        from app.common.exceptions import BadRequestException

        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user = AsyncMock(return_value=0)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            with pytest.raises(BadRequestException, match="Invalid resource_type"):
                await service.create_token(
                    user_id="user-1",
                    name="test",
                    scopes=["skills:read"],
                    resource_type="unknown",
                    resource_id=uuid.uuid4(),
                )

    @pytest.mark.asyncio
    async def test_create_accepts_valid_resource_binding(self):
        """Should succeed with valid resource_type + resource_id pair."""
        db = _mock_db()
        with patch("app.services.platform_token_service.PlatformTokenRepository") as MockRepo:
            MockRepo.return_value.count_active_by_user = AsyncMock(return_value=0)
            from app.services.platform_token_service import PlatformTokenService

            service = PlatformTokenService(db)
            record, raw_token = await service.create_token(
                user_id="user-1",
                name="test",
                scopes=["skills:execute"],
                resource_type="skill",
                resource_id=uuid.uuid4(),
            )
            assert raw_token.startswith("sk_")
