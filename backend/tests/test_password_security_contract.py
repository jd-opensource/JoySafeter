import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.joysafeter_api.api.v1.auth import ChangePasswordRequest, RegisterRequest, ResetPasswordRequest
from app.joysafeter_domain.services.joysafeter_auth_service import AuthService
from app.joysafeter_shared.common.app_errors import AuthenticationError
from app.joysafeter_shared.security import (
    get_password_hash,
    hash_security_token,
    is_legacy_password_hash,
    verify_password,
)

pytestmark = pytest.mark.no_db


def test_password_hash_is_salted_and_not_replayable():
    password = "Correct-Horse1!"

    first_hash = get_password_hash(password)
    second_hash = get_password_hash(password)

    assert first_hash != second_hash
    assert first_hash.startswith("$2")
    assert verify_password(password, first_hash)
    assert not verify_password("Wrong-Horse1!", first_hash)


def test_legacy_sha256_hash_accepts_raw_password_but_not_hash_replay():
    password = "Legacy-Password1!"
    legacy_hash = hashlib.sha256(password.encode()).hexdigest()

    assert is_legacy_password_hash(legacy_hash)
    assert verify_password(password, legacy_hash)
    assert not verify_password(legacy_hash, legacy_hash)


def test_one_time_token_digest_is_stable_without_storing_raw_token():
    token = "email-token-secret"

    digest = hash_security_token(token)

    assert digest == hash_security_token(token)
    assert digest != token
    assert token not in digest


@pytest.mark.parametrize(
    "password",
    [
        "Short1!",
        "lowercase1!",
        "UPPERCASE1!",
        "NoNumbers!",
        "NoSpecial1",
    ],
)
def test_registration_rejects_passwords_outside_server_policy(password: str):
    with pytest.raises(ValidationError):
        RegisterRequest(email="user@example.com", name="User", password=password)


def test_password_reset_and_change_share_server_policy():
    password = "Strong-Password1!"

    reset = ResetPasswordRequest(token="token", new_password=password)
    change = ChangePasswordRequest(old_password="Old-Password1!", new_password=password)

    assert reset.new_password == password
    assert change.old_password == "Old-Password1!"


@pytest.mark.asyncio
async def test_change_password_requires_the_current_password():
    service = AuthService(AsyncMock())
    service.commit = AsyncMock()
    service._revoke_user_sessions = AsyncMock()
    user = SimpleNamespace(id="user-1", is_active=True, hashed_password=get_password_hash("Current-Password1!"))

    with pytest.raises(AuthenticationError):
        await service.change_password_for_current_user(
            user=user,
            old_password="Wrong-Password1!",
            new_password="New-Password1!",
        )

    service.commit.assert_not_awaited()
    service._revoke_user_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_change_password_rehashes_and_revokes_sessions():
    service = AuthService(AsyncMock())
    service.commit = AsyncMock()
    service._revoke_user_sessions = AsyncMock()
    user = SimpleNamespace(id="user-1", is_active=True, hashed_password=get_password_hash("Current-Password1!"))

    await service.change_password_for_current_user(
        user=user,
        old_password="Current-Password1!",
        new_password="New-Password1!",
    )

    assert verify_password("New-Password1!", user.hashed_password)
    assert not verify_password("Current-Password1!", user.hashed_password)
    service.commit.assert_awaited_once()
    service._revoke_user_sessions.assert_awaited_once_with("user-1")
