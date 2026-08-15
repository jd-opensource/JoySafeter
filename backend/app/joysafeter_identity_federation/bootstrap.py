"""Identity federation configuration bootstrap."""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

from app.joysafeter_shared.config.settings import settings

from .infrastructure.config import CompiledFederationConfiguration, compile_federation_configuration
from .infrastructure.protocols.base import ProtocolSchemaRegistry
from .infrastructure.protocols.schemas import JD_SSO_PROTOCOL_DEFINITION, OAUTH2_PROTOCOL_DEFINITION

_configuration: CompiledFederationConfiguration | None = None


def _config_path() -> Path:
    if settings.identity_federation_config_path:
        return Path(settings.identity_federation_config_path)
    return Path(__file__).resolve().parents[2] / "config" / "identity_federation_providers.yaml"


def _schema_registry() -> ProtocolSchemaRegistry:
    registry = ProtocolSchemaRegistry()
    registry.register(OAUTH2_PROTOCOL_DEFINITION)
    registry.register(JD_SSO_PROTOCOL_DEFINITION)
    return registry


def initialize_identity_federation_configuration(
    *, force: bool = False
) -> CompiledFederationConfiguration:
    global _configuration

    if _configuration is None or force:
        _configuration = compile_federation_configuration(
            config_path=_config_path(),
            active_provider_names=settings.identity_federation_providers,
            login_mode=settings.identity_federation_login_mode,
            application_environment=settings.environment,
            schema_registry=_schema_registry(),
            environ=os.environ,
        )
        logger.bind(
            provider_ids=[descriptor.id.value for descriptor in _configuration.registry.list_public()],
            login_mode=_configuration.registry.settings.login_mode.value,
        ).info("Identity federation configuration initialized")

    return _configuration


def get_identity_federation_configuration() -> CompiledFederationConfiguration:
    return initialize_identity_federation_configuration()
