from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_object_session, async_sessionmaker

from app.joysafeter_domain.models.joysafeter_auth import AuthUser
from app.joysafeter_domain.models.joysafeter_oauth_account import OAuthAccount
from app.joysafeter_domain.repositories.joysafeter_auth_user import AuthUserRepository
from app.joysafeter_identity_federation.application.accounts import FederatedAccountService
from app.joysafeter_identity_federation.domain.errors import FederationError
from app.joysafeter_identity_federation.domain.models import FederatedPrincipal, ProviderId
from app.joysafeter_identity_federation.domain.policies import AccountLinkPolicy
from app.joysafeter_identity_federation.infrastructure.account_gateway import (
    SqlAlchemyFederatedAccountGateway,
)
from app.joysafeter_shared.ids import OAuthAccountId, UserId


def _principal(
    *,
    provider: str = "github",
    subject: str = "subject-1",
    email: str | None = "user@example.com",
    email_verified: bool = True,
    claims: dict[str, object] | None = None,
) -> FederatedPrincipal:
    return FederatedPrincipal(
        provider_id=ProviderId(provider),
        subject=subject,
        email=email,
        email_verified=email_verified,
        display_name="Federated User",
        avatar_url="https://images.example/avatar.png",
        claims=claims or {"sub": subject},
    )


async def _create_user(
    db_session: AsyncSession,
    *,
    email: str,
    active: bool,
    hashed_password: str | None = "password-hash",
) -> AuthUser:
    user = AuthUser(
        id=UserId.new(),
        email=email,
        name=email.split("@")[0],
        hashed_password=hashed_password,
        email_verified=True,
        is_active=active,
    )
    db_session.add(user)
    await db_session.commit()
    return user


async def _create_binding(
    db_session: AsyncSession,
    user_id: UserId,
    *,
    provider: str,
    subject: str,
    email: str | None = None,
) -> OAuthAccount:
    binding = OAuthAccount(
        id=OAuthAccountId.new(),
        user_id=user_id,
        provider=provider,
        provider_account_id=subject,
        email=email,
        raw_userinfo={"sub": subject},
    )
    db_session.add(binding)
    await db_session.commit()
    return binding


async def _oauth_binding_count(db_session: AsyncSession, user_id: UserId) -> int:
    result = await db_session.execute(
        select(func.count()).select_from(OAuthAccount).where(OAuthAccount.user_id == user_id)
    )
    return int(result.scalar_one())


def _raise_unique_conflict_after_binding(
    winner_id: UserId,
) -> Callable[[OAuthAccount], Awaitable[None]]:
    async def flush_with_competing_binding(binding: OAuthAccount) -> None:
        db_session = async_object_session(binding)
        assert db_session is not None
        assert db_session.bind is not None
        competing_sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)
        async with competing_sessions() as competing_session:
            competing_session.add(
                OAuthAccount(
                    id=OAuthAccountId.new(),
                    user_id=winner_id,
                    provider=binding.provider,
                    provider_account_id=binding.provider_account_id,
                    email=binding.email,
                    raw_userinfo=binding.raw_userinfo,
                )
            )
            await competing_session.commit()
        await db_session.flush()

    return flush_with_competing_binding


@pytest.mark.asyncio
async def test_existing_subject_binding_wins_over_email(db_session) -> None:
    bound_user = await _create_user(db_session, email="bound@example.com", active=True)
    await _create_binding(db_session, bound_user.id, provider="github", subject="subject-1")
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(subject="subject-1", email="different@example.com", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )

    assert resolved.user_id == bound_user.id
    assert resolved.is_new_user is False


@pytest.mark.asyncio
async def test_verified_email_links_active_existing_user(db_session) -> None:
    existing = await _create_user(db_session, email="user@example.com", active=True)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(email="User@Example.com", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )

    assert resolved.user_id == existing.id
    assert await _oauth_binding_count(db_session, existing.id) == 1


@pytest.mark.asyncio
async def test_verified_email_matches_normalized_existing_email(db_session) -> None:
    existing = await _create_user(db_session, email="User@Example.com", active=True)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(email=" user@example.com ", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )

    assert resolved.user_id == existing.id
    assert resolved.is_new_user is False


@pytest.mark.asyncio
async def test_unverified_email_never_links_existing_user(db_session) -> None:
    existing = await _create_user(db_session, email="user@example.com", active=True)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    with pytest.raises(FederationError) as exc_info:
        await gateway.resolve_or_create(
            _principal(email="user@example.com", email_verified=False),
            AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
        )

    assert exc_info.value.code == "FEDERATION_ACCOUNT_LINK_REQUIRED"
    assert await _oauth_binding_count(db_session, existing.id) == 0


@pytest.mark.asyncio
async def test_inactive_email_never_links_existing_user(db_session) -> None:
    existing = await _create_user(db_session, email="user@example.com", active=False)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    with pytest.raises(FederationError) as exc_info:
        await gateway.resolve_or_create(
            _principal(email="user@example.com", email_verified=True),
            AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
        )

    assert exc_info.value.code == "FEDERATION_ACCOUNT_LINK_REQUIRED"
    assert await _oauth_binding_count(db_session, existing.id) == 0


@pytest.mark.asyncio
async def test_registration_disabled_rejects_unknown_subject(db_session) -> None:
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    with pytest.raises(FederationError) as exc_info:
        await gateway.resolve_or_create(
            _principal(email="new@example.com", email_verified=True),
            AccountLinkPolicy(allow_registration=False, auto_link_by_email=False),
        )

    assert exc_info.value.code == "FEDERATION_REGISTRATION_DISABLED"


@pytest.mark.asyncio
async def test_registration_preserves_external_email_verification_state(db_session) -> None:
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(email="new@example.com", email_verified=False),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=False),
    )
    user = await AuthUserRepository(db_session).get_by_id(resolved.user_id)

    assert resolved.is_new_user is True
    assert user is not None
    assert user.email_verified is False


@pytest.mark.asyncio
async def test_registration_requires_an_email(db_session) -> None:
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    with pytest.raises(FederationError) as exc_info:
        await gateway.resolve_or_create(
            _principal(email=None, email_verified=False),
            AccountLinkPolicy(allow_registration=True, auto_link_by_email=False),
        )

    assert exc_info.value.code == "FEDERATION_EMAIL_REQUIRED"


@pytest.mark.asyncio
async def test_new_binding_stores_only_sanitized_claims(db_session) -> None:
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    resolved = await gateway.resolve_or_create(
        _principal(
            email="new@example.com",
            claims={
                "sub": "subject-1",
                "role": "developer",
                "access_token": "access-secret",
                "refresh_token": "refresh-secret",
                "id_token": "id-secret",
                "code": "authorization-secret",
                "ticket": "ticket-secret",
                "cookies": {"session": "cookie-secret"},
            },
        ),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=False),
    )
    result = await db_session.execute(select(OAuthAccount).where(OAuthAccount.user_id == resolved.user_id))
    binding = result.scalar_one()

    assert binding.access_token is None
    assert binding.refresh_token is None
    assert binding.token_expires_at is None
    assert binding.raw_userinfo == {"sub": "subject-1", "role": "developer"}


@pytest.mark.asyncio
async def test_subject_binding_race_reloads_the_winning_binding(db_session, monkeypatch) -> None:
    winner = await _create_user(db_session, email="winner@example.com", active=True)
    gateway = SqlAlchemyFederatedAccountGateway(db_session)
    monkeypatch.setattr(gateway, "_flush_new_binding", _raise_unique_conflict_after_binding(winner.id))

    resolved = await gateway.resolve_or_create(
        _principal(subject="subject-1", email="winner@example.com", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )

    assert resolved.user_id == winner.id
    assert resolved.is_new_user is False


@pytest.mark.asyncio
async def test_binding_race_does_not_rollback_unrelated_outer_work(db_session, monkeypatch) -> None:
    winner = await _create_user(db_session, email="winner@example.com", active=True)
    winner.name = "Updated outside savepoint"
    gateway = SqlAlchemyFederatedAccountGateway(db_session)
    monkeypatch.setattr(gateway, "_flush_new_binding", _raise_unique_conflict_after_binding(winner.id))

    await gateway.resolve_or_create(
        _principal(subject="subject-1", email="winner@example.com", email_verified=True),
        AccountLinkPolicy(allow_registration=True, auto_link_by_email=True),
    )
    await db_session.commit()
    await db_session.refresh(winner)

    assert winner.name == "Updated outside savepoint"


@pytest.mark.asyncio
async def test_list_accounts_returns_domain_views(db_session) -> None:
    user = await _create_user(db_session, email="user@example.com", active=True)
    binding = await _create_binding(
        db_session,
        user.id,
        provider="github",
        subject="subject-1",
        email="User@Example.com",
    )
    gateway = SqlAlchemyFederatedAccountGateway(db_session)

    accounts = await gateway.list_accounts(user.id)

    assert len(accounts) == 1
    assert accounts[0].id == binding.id
    assert accounts[0].provider_id == ProviderId("github")
    assert accounts[0].subject == "subject-1"
    assert accounts[0].email == "user@example.com"
    assert accounts[0].created_at == binding.created_at


@pytest.mark.asyncio
async def test_unlink_rejects_only_login_method(db_session) -> None:
    user = await _create_user(db_session, email="sso@example.com", active=True, hashed_password=None)
    await _create_binding(db_session, user.id, provider="jd", subject="42")
    service = FederatedAccountService(SqlAlchemyFederatedAccountGateway(db_session), db_session.commit)

    with pytest.raises(FederationError) as exc_info:
        await service.unlink(user.id, ProviderId("jd"))

    assert exc_info.value.code == "FEDERATION_LAST_ACCOUNT_UNLINK_FORBIDDEN"


@pytest.mark.asyncio
async def test_service_commits_successful_unlink(db_session) -> None:
    user = await _create_user(db_session, email="user@example.com", active=True)
    await _create_binding(db_session, user.id, provider="github", subject="subject-1")
    commits = 0

    async def commit() -> None:
        nonlocal commits
        commits += 1
        await db_session.commit()

    service = FederatedAccountService(SqlAlchemyFederatedAccountGateway(db_session), commit)

    removed = await service.unlink(user.id, ProviderId("github"))

    assert removed is True
    assert commits == 1
    assert await _oauth_binding_count(db_session, user.id) == 0


@pytest.mark.asyncio
async def test_service_does_not_commit_missing_unlink(db_session) -> None:
    user = await _create_user(db_session, email="user@example.com", active=True)
    commits = 0

    async def commit() -> None:
        nonlocal commits
        commits += 1

    service = FederatedAccountService(SqlAlchemyFederatedAccountGateway(db_session), commit)

    removed = await service.unlink(user.id, ProviderId("github"))

    assert removed is False
    assert commits == 0
