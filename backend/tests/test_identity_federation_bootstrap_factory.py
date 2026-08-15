from dataclasses import FrozenInstanceError, fields

import pytest

from app.joysafeter_identity_federation.bootstrap import (
    build_federated_account_service,
    build_federated_login_coordinator,
    get_federation_provider_view,
    get_identity_federation_runtime,
    initialize_identity_federation,
)
from app.joysafeter_identity_federation.domain.models import ProtocolId
from app.joysafeter_identity_federation.infrastructure import config as config_module
from app.joysafeter_identity_federation.infrastructure.account_gateway import (
    SqlAlchemyFederatedAccountGateway,
)
from app.joysafeter_identity_federation.infrastructure.protocols.jd_sso import JDSSOAdapter
from app.joysafeter_identity_federation.infrastructure.protocols.oauth2 import (
    OAuth2Adapter,
    direct_http_client_factory,
)
from app.joysafeter_identity_federation.infrastructure.session_gateway import (
    JoySafeterAuthSessionGateway,
)
from app.joysafeter_identity_federation.infrastructure.state_store import RedisLoginAttemptStore
from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.config.settings import settings

pytestmark = pytest.mark.no_db


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1


@pytest.fixture(autouse=True)
def _configure_federation(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        config_module,
        "_resolve_endpoint_addresses",
        lambda _hostname, _port: ("93.184.216.34",),
    )
    path = tmp_path / "providers.yaml"
    path.write_text(
        """
version: 1
providers:
  jd:
    display_name: JD SSO
    icon: building
    protocol: jd_sso
    client_id: ${JD_CLIENT_ID}
    client_secret: ${JD_CLIENT_SECRET}
    authorize_url: ${JD_AUTHORIZE_URL}
    userinfo_url: ${JD_USERINFO_URL}
    scope: openid email
    user_mapping:
      id: userId
      email: email
      name: username
      avatar: ""
  github:
    display_name: GitHub
    icon: github
    protocol: oauth2
    template: github
    client_id: ${GITHUB_CLIENT_ID}
    client_secret: ${GITHUB_CLIENT_SECRET}
settings:
  default_redirect_url: /managed/quickstart
  allow_registration: true
  auto_link_by_email: true
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "identity_federation_config_path", str(path))
    monkeypatch.setattr(settings, "identity_federation_providers", "jd,github")
    monkeypatch.setattr(settings, "identity_federation_login_mode", "redirect")
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "secret_key", "task-14-application-secret")
    monkeypatch.setenv("JD_CLIENT_ID", "jd-client")
    monkeypatch.setenv("JD_CLIENT_SECRET", "jd-secret")
    monkeypatch.setenv("JD_AUTHORIZE_URL", "https://sso.jd.com/login")
    monkeypatch.setenv("JD_USERINFO_URL", "https://sso.jd.com/verifyTicket")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "github-client")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "github-secret")


def test_runtime_initialization_caches_secure_concrete_components() -> None:
    runtime = initialize_identity_federation(force=True)

    assert initialize_identity_federation() is runtime
    assert get_identity_federation_runtime() is runtime
    assert [provider.id.value for provider in runtime.registry.list_public()] == ["jd", "github"]

    oauth2 = runtime.adapters.require(ProtocolId.OAUTH2)
    jd_sso = runtime.adapters.require(ProtocolId.JD_SSO)
    assert isinstance(oauth2, OAuth2Adapter)
    assert isinstance(jd_sso, JDSSOAdapter)
    assert oauth2._client_factory is direct_http_client_factory
    assert jd_sso._client_factory is direct_http_client_factory
    assert jd_sso._correlation_codec.cookie_name == "joysafeter_federation_attempt"

    assert isinstance(runtime.attempt_store, RedisLoginAttemptStore)
    assert runtime.attempt_store._redis_factory.__self__ is RedisClient
    assert runtime.attempt_store._redis_factory.__func__ is RedisClient.get_client.__func__

    with pytest.raises(FrozenInstanceError):
        runtime.registry = runtime.registry


def test_provider_view_is_frozen_ordered_and_public_only() -> None:
    runtime = initialize_identity_federation(force=True)

    view = get_federation_provider_view(runtime)

    assert view.login_mode == "redirect"
    assert get_federation_provider_view() == view
    assert [(provider.id, provider.display_name, provider.icon) for provider in view.providers] == [
        ("jd", "JD SSO", "building"),
        ("github", "GitHub", "github"),
    ]
    assert tuple(field.name for field in fields(view)) == ("providers", "login_mode")
    assert tuple(field.name for field in fields(view.providers[0])) == ("id", "display_name", "icon")
    assert isinstance(view.providers, tuple)
    assert all(isinstance(provider.id, str) for provider in view.providers)
    assert not hasattr(view.providers[0], "protocol")
    assert not hasattr(view.providers[0], "client_id")
    assert not hasattr(view.providers[0], "client_secret")
    assert not hasattr(view.providers[0], "settings")

    with pytest.raises(FrozenInstanceError):
        view.login_mode = "chooser"


def test_coordinator_factory_reuses_runtime_and_creates_fresh_gateways() -> None:
    runtime = initialize_identity_federation(force=True)
    first_db = _FakeAsyncSession()
    second_db = _FakeAsyncSession()

    first = build_federated_login_coordinator(first_db)
    second = build_federated_login_coordinator(second_db)

    assert first._registry is runtime.registry
    assert second._registry is runtime.registry
    assert first._adapters is runtime.adapters
    assert second._adapters is runtime.adapters
    assert first._attempt_store is runtime.attempt_store
    assert second._attempt_store is runtime.attempt_store

    assert isinstance(first._account_gateway, SqlAlchemyFederatedAccountGateway)
    assert isinstance(second._account_gateway, SqlAlchemyFederatedAccountGateway)
    assert first._account_gateway is not second._account_gateway
    assert first._account_gateway._db_session is first_db
    assert second._account_gateway._db_session is second_db

    assert isinstance(first._session_gateway, JoySafeterAuthSessionGateway)
    assert isinstance(second._session_gateway, JoySafeterAuthSessionGateway)
    assert first._session_gateway is not second._session_gateway
    assert first._session_gateway._db_session is first_db
    assert second._session_gateway._db_session is second_db


def test_account_service_factory_creates_fresh_gateway_for_supplied_session() -> None:
    initialize_identity_federation(force=True)
    first_db = _FakeAsyncSession()
    second_db = _FakeAsyncSession()

    first = build_federated_account_service(first_db)
    second = build_federated_account_service(second_db)

    assert isinstance(first._gateway, SqlAlchemyFederatedAccountGateway)
    assert isinstance(second._gateway, SqlAlchemyFederatedAccountGateway)
    assert first._gateway is not second._gateway
    assert first._gateway._db_session is first_db
    assert second._gateway._db_session is second_db
    assert first._commit.__self__ is first_db
    assert second._commit.__self__ is second_db
