"""Identity federation application bootstrap."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.config.settings import settings

from .application.accounts import FederatedAccountService as _FederatedAccountService
from .application.coordinator import FederatedLoginCoordinator as _FederatedLoginCoordinator
from .domain.ports import LoginAttemptStore, ProtocolAdapterResolver, ProviderRegistryPort
from .infrastructure.account_gateway import SqlAlchemyFederatedAccountGateway as _SqlAlchemyFederatedAccountGateway
from .infrastructure.config import CompiledFederationConfiguration as _CompiledFederationConfiguration
from .infrastructure.config import compile_federation_configuration as _compile_federation_configuration
from .infrastructure.correlation import SignedCorrelationCodec as _SignedCorrelationCodec
from .infrastructure.protocols.base import ProtocolAdapterRegistry as _ProtocolAdapterRegistry
from .infrastructure.protocols.base import ProtocolSchemaRegistry as _ProtocolSchemaRegistry
from .infrastructure.protocols.jd_sso import JDSSOAdapter as _JDSSOAdapter
from .infrastructure.protocols.oauth2 import OAuth2Adapter as _OAuth2Adapter
from .infrastructure.protocols.oauth2 import direct_http_client_factory as _http_client_factory
from .infrastructure.protocols.schemas import JD_SSO_PROTOCOL_DEFINITION as _JD_SSO_PROTOCOL_DEFINITION
from .infrastructure.protocols.schemas import OAUTH2_PROTOCOL_DEFINITION as _OAUTH2_PROTOCOL_DEFINITION
from .infrastructure.session_gateway import JoySafeterAuthSessionGateway as _JoySafeterAuthSessionGateway
from .infrastructure.state_store import RedisLoginAttemptStore as _RedisLoginAttemptStore


@dataclass(frozen=True, slots=True)
class FederationRuntime:
    registry: ProviderRegistryPort
    adapters: ProtocolAdapterResolver
    attempt_store: LoginAttemptStore


@dataclass(frozen=True, slots=True)
class _FederationCache:
    configuration: _CompiledFederationConfiguration | None = None
    runtime: FederationRuntime | None = None


_cache = _FederationCache()


@dataclass(frozen=True, slots=True)
class FederationProviderInfo:
    id: str
    display_name: str
    icon: str


@dataclass(frozen=True, slots=True)
class FederationProviderView:
    providers: tuple[FederationProviderInfo, ...]
    login_mode: str


def _config_path() -> Path:
    if settings.identity_federation_config_path:
        return Path(settings.identity_federation_config_path)
    return Path(__file__).resolve().parents[2] / "config" / "identity_federation_providers.yaml"


def _schema_registry() -> _ProtocolSchemaRegistry:
    registry = _ProtocolSchemaRegistry()
    registry.register(_OAUTH2_PROTOCOL_DEFINITION)
    registry.register(_JD_SSO_PROTOCOL_DEFINITION)
    return registry


def _compile_configuration() -> _CompiledFederationConfiguration:
    return _compile_federation_configuration(
        config_path=_config_path(),
        active_provider_names=settings.identity_federation_providers,
        login_mode=settings.identity_federation_login_mode,
        application_environment=settings.environment,
        schema_registry=_schema_registry(),
        environ=os.environ,
    )


def _log_configuration(configuration: _CompiledFederationConfiguration) -> None:
    logger.bind(
        provider_ids=[descriptor.id.value for descriptor in configuration.registry.list_public()],
        login_mode=configuration.registry.settings.login_mode.value,
    ).info("Identity federation configuration initialized")


def _build_runtime(configuration: _CompiledFederationConfiguration) -> FederationRuntime:
    correlation = _SignedCorrelationCodec(
        secret=settings.secret_key.encode("utf-8"),
        cookie_name="joysafeter_federation_attempt",
    )
    adapters = _ProtocolAdapterRegistry()
    adapters.register(_OAuth2Adapter(client_factory=_http_client_factory))
    adapters.register(
        _JDSSOAdapter(
            correlation_codec=correlation,
            client_factory=_http_client_factory,
        )
    )
    return FederationRuntime(
        registry=configuration.registry,
        adapters=adapters,
        attempt_store=_RedisLoginAttemptStore(RedisClient.get_client),
    )


def initialize_identity_federation_configuration(*, force: bool = False) -> _CompiledFederationConfiguration:
    global _cache

    if _cache.configuration is None or force:
        configuration = _compile_configuration()
        _cache = _FederationCache(configuration=configuration)
        _log_configuration(configuration)

    assert _cache.configuration is not None
    return _cache.configuration


def get_identity_federation_configuration() -> _CompiledFederationConfiguration:
    return initialize_identity_federation_configuration()


def initialize_identity_federation(*, force: bool = False) -> FederationRuntime:
    global _cache

    if _cache.runtime is None or force:
        configuration = _compile_configuration() if force or _cache.configuration is None else _cache.configuration
        runtime = _build_runtime(configuration)
        configuration_replaced = configuration is not _cache.configuration
        _cache = _FederationCache(configuration=configuration, runtime=runtime)
        if configuration_replaced:
            _log_configuration(configuration)
        logger.info("Identity federation runtime initialized")

    assert _cache.runtime is not None
    return _cache.runtime


def get_identity_federation_runtime() -> FederationRuntime:
    return initialize_identity_federation()


def get_federation_provider_view(runtime: FederationRuntime | None = None) -> FederationProviderView:
    registry = (runtime or get_identity_federation_runtime()).registry
    return FederationProviderView(
        providers=tuple(
            FederationProviderInfo(
                id=provider.id.value,
                display_name=provider.display_name,
                icon=provider.icon,
            )
            for provider in registry.list_public()
        ),
        login_mode=registry.settings.login_mode.value,
    )


def build_federated_login_coordinator(db: AsyncSession) -> _FederatedLoginCoordinator:
    runtime = get_identity_federation_runtime()
    return _FederatedLoginCoordinator(
        registry=runtime.registry,
        adapters=runtime.adapters,
        attempt_store=runtime.attempt_store,
        account_gateway=_SqlAlchemyFederatedAccountGateway(db),
        session_gateway=_JoySafeterAuthSessionGateway(db),
    )


def build_federated_account_service(db: AsyncSession) -> _FederatedAccountService:
    return _FederatedAccountService(
        gateway=_SqlAlchemyFederatedAccountGateway(db),
        commit=db.commit,
    )
