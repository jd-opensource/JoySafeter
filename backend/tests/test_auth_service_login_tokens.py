from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.services.joysafeter_auth_service import AuthService

pytestmark = pytest.mark.no_db

_ACCESS_EXPIRES_AT = datetime(2026, 8, 15, 12, 30, tzinfo=timezone.utc)
_REFRESH_EXPIRES_AT = datetime(2026, 8, 22, 12, 30, tzinfo=timezone.utc)


class _TokenIssuingAuthService(AuthService):
    def __init__(self) -> None:
        pass

    async def _issue_jwt_tokens(self, user_id: str) -> tuple[str, str, str, datetime, datetime]:
        assert user_id == "user-1"
        return "access", "refresh", "csrf", _ACCESS_EXPIRES_AT, _REFRESH_EXPIRES_AT


@pytest.mark.asyncio
async def test_issue_login_tokens_exposes_calculated_timezone_aware_expiries() -> None:
    user = SimpleNamespace(
        id="user-1",
        email="user@example.com",
        name="User",
        image=None,
        email_verified=True,
        is_super_user=False,
        created_at=None,
        updated_at=None,
    )

    token_result = await _TokenIssuingAuthService().issue_login_tokens(user)

    assert token_result["access_token"] == "access"
    assert token_result["refresh_token"] == "refresh"
    assert token_result["csrf_token"] == "csrf"
    assert token_result["access_expires_at"] is _ACCESS_EXPIRES_AT
    assert token_result["refresh_expires_at"] is _REFRESH_EXPIRES_AT
    assert _ACCESS_EXPIRES_AT.utcoffset() is not None
    assert _REFRESH_EXPIRES_AT.utcoffset() is not None
