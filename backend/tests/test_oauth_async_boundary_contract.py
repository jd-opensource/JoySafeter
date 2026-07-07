from types import SimpleNamespace

import pytest

from app.joysafeter_api.api.v1 import oauth as oauth_api
from app.joysafeter_domain.services import joysafeter_auth_service as auth_service_module
from app.joysafeter_domain.services.joysafeter_auth_service import AuthService, OAuthService
from app.joysafeter_shared.common.app_errors import InvalidRequestError


class _FakeLogger:
    def __init__(self):
        self.bound: dict | None = None
        self.messages: list[tuple[str, str]] = []

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def warning(self, message: str):
        self.messages.append(("warning", message))

    def error(self, message: str):
        self.messages.append(("error", message))

    def info(self, message: str):
        self.messages.append(("info", message))

    def debug(self, message: str):
        self.messages.append(("debug", message))


class _FailingRedis:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    async def get(key: str):
        raise RuntimeError("redis unavailable")


class _FailingSetRedis:
    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    async def set(key: str, value: str, expire: int):
        raise RuntimeError("redis unavailable")


class _FailingDeleteRedis:
    async def delete(self, key: str):
        raise RuntimeError("redis unavailable")


class _SessionService:
    def __init__(self):
        self.invalidated: list[str] = []

    async def invalidate_session(self, token: str):
        self.invalidated.append(token)


class _FakeOAuthConfig:
    def __init__(self, provider):
        self._provider = provider

    def get_provider(self, provider_name: str):
        return self._provider

    async def discover_oidc_config(self, issuer: str):
        raise RuntimeError("issuer unavailable")


def _oauth_service(provider) -> OAuthService:
    svc = object.__new__(OAuthService)
    svc.oauth_config = _FakeOAuthConfig(provider)
    return svc


def _auth_service() -> AuthService:
    svc = object.__new__(AuthService)
    svc.session_service = _SessionService()
    return svc


@pytest.mark.asyncio
async def test_oauth_api_state_validate_failure_logs_structured_boundary_error(monkeypatch):
    fake_logger = _FakeLogger()
    monkeypatch.setattr(oauth_api, "RedisClient", _FailingRedis)
    monkeypatch.setattr(oauth_api, "logger", fake_logger)

    state_data, callback_url = await oauth_api._validate_state(
        "state-1234567890",
        SimpleNamespace(settings=SimpleNamespace(default_redirect_url="/managed/quickstart")),
    )

    assert state_data == {}
    assert callback_url == "/managed/quickstart"
    assert fake_logger.messages == [("warning", "[OAuthAPI] Failed to validate state")]
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "OAUTH_API_STATE_VALIDATE_FAILED",
            "message": "Failed to validate OAuth state from Redis",
            "data": {
                "boundary": "oauth_api",
                "operation": "validate_state",
                "state_prefix": "state-1234567890",
            },
            "source": "api",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


@pytest.mark.asyncio
async def test_oauth_service_state_store_failure_logs_structured_boundary_error(monkeypatch):
    fake_logger = _FakeLogger()
    monkeypatch.setattr(auth_service_module, "RedisClient", _FailingSetRedis)
    monkeypatch.setattr(auth_service_module, "logger", fake_logger)
    svc = _oauth_service(
        SimpleNamespace(
            authorize_url="https://issuer.example/authorize",
            issuer=None,
            client_id="client-1",
            client_secret="secret-1",
            scope="openid email",
        )
    )

    authorization_url, state = await svc.generate_authorization_url(
        provider_name="oidc",
        redirect_uri="https://app.example/callback",
        state="state-1",
    )

    assert state == "state-1"
    assert authorization_url.startswith("https://issuer.example/authorize?")
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "OAUTH_SERVICE_STATE_STORE_FAILED",
            "message": "Failed to store OAuth state in Redis",
            "data": {
                "boundary": "oauth_service",
                "operation": "store_state",
                "provider_name": "oidc",
                "state_key": "oauth_state:state-1",
            },
            "source": "runtime",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


@pytest.mark.asyncio
async def test_oauth_service_oidc_discovery_failure_logs_structured_boundary_error(monkeypatch):
    fake_logger = _FakeLogger()
    monkeypatch.setattr(auth_service_module, "RedisClient", SimpleNamespace(is_available=lambda: False))
    monkeypatch.setattr(auth_service_module, "logger", fake_logger)
    svc = _oauth_service(
        SimpleNamespace(
            authorize_url=None,
            issuer="https://issuer.example",
            client_id="client-1",
            client_secret="secret-1",
            scope="openid email",
        )
    )

    with pytest.raises(InvalidRequestError) as exc_info:
        await svc.generate_authorization_url(
            provider_name="oidc",
            redirect_uri="https://app.example/callback",
            state="state-1",
        )

    assert exc_info.value.code == "OAUTH_DISCOVERY_FAILED"
    assert fake_logger.messages == [("error", "[OAuthService] OIDC Discovery failed")]
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "OAUTH_AUTHORIZATION_DISCOVERY_UPSTREAM_FAILED",
            "message": "OAuth authorization endpoint discovery failed",
            "data": {
                "boundary": "oauth_service",
                "operation": "discover_authorization_endpoint",
                "provider_name": "oidc",
                "issuer": "https://issuer.example",
            },
            "source": "upstream",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


@pytest.mark.asyncio
async def test_auth_refresh_token_rotate_failure_logs_structured_boundary_error(monkeypatch):
    fake_logger = _FakeLogger()
    monkeypatch.setattr(auth_service_module, "logger", fake_logger)
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.is_available",
        staticmethod(lambda: True),
    )
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: _FailingDeleteRedis()),
    )
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.set",
        staticmethod(lambda key, value, expire: None),
    )
    svc = _auth_service()

    await svc._rotate_refresh_token("secret-refresh-token", "user-1")

    assert svc.session_service.invalidated == ["refresh:secret-refresh-token"]
    assert fake_logger.messages == [("debug", "Failed to rotate refresh token in Redis")]
    error = fake_logger.bound["error"]
    assert error["code"] == "AUTH_REFRESH_TOKEN_REDIS_ROTATE_FAILED"
    assert error["data"] == {
        "boundary": "auth_service",
        "operation": "rotate_refresh_token",
        "user_id": "user-1",
    }
    assert "secret-refresh-token" not in str(error)
