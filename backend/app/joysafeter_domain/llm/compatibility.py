from __future__ import annotations

import logging
from collections.abc import Mapping

from app.joysafeter_domain.llm.catalog import (
    CredentialProfile,
    EngineCapability,
    LlmCatalogError,
    ProviderDefinition,
    ProviderProtocolBinding,
    get_llm_catalog,
)
from app.joysafeter_domain.schemas.joysafeter_credential import CredentialKind
from app.joysafeter_shared.common.app_errors import InvalidRequestError

logger = logging.getLogger(__name__)


class LlmCompatibilityError(InvalidRequestError):
    pass


def _engine(engine_id: str) -> EngineCapability:
    try:
        engine = get_llm_catalog().engine(engine_id)
    except LlmCatalogError as exc:
        raise LlmCompatibilityError(
            code="LLM_ENGINE_UNKNOWN",
            message=f"Unknown LLM engine: {engine_id}",
            data={"engine_kind": engine_id},
            user_action="fix_input",
        ) from exc
    if not engine.enabled:
        raise LlmCompatibilityError(
            code="LLM_ENGINE_DISABLED",
            message=f"LLM engine is disabled: {engine_id}",
            data={"engine_kind": engine_id},
            user_action="fix_input",
        )
    return engine


def _provider(provider_id: str) -> ProviderDefinition:
    try:
        provider = get_llm_catalog().provider(provider_id)
    except LlmCatalogError as exc:
        raise LlmCompatibilityError(
            code="LLM_PROVIDER_UNKNOWN",
            message=f"Unknown LLM provider: {provider_id}",
            data={"provider": provider_id},
            user_action="fix_input",
        ) from exc
    if not provider.enabled:
        raise LlmCompatibilityError(
            code="LLM_PROVIDER_DISABLED",
            message=f"LLM provider is disabled: {provider_id}",
            data={"provider": provider_id},
            user_action="fix_input",
        )
    return provider


def validate_engine(engine_id: str) -> EngineCapability:
    return _engine(engine_id)


def _validate_protocol_id(protocol_id: str) -> None:
    try:
        get_llm_catalog().protocol(protocol_id)
    except LlmCatalogError as exc:
        raise LlmCompatibilityError(
            code="LLM_PROTOCOL_UNKNOWN",
            message=f"Unknown LLM protocol: {protocol_id}",
            data={"protocol": protocol_id},
            user_action="fix_input",
        ) from exc


def compatible_protocol_ids(engine_id: str, provider_id: str | None = None) -> list[str]:
    engine = _engine(engine_id)
    if provider_id is None:
        return list(engine.supported_protocol_ids)
    provider = _provider(provider_id)
    provider_protocol_ids = {binding.protocol_id for binding in provider.protocol_bindings}
    return [
        protocol_id
        for protocol_id in engine.supported_protocol_ids
        if protocol_id in provider_protocol_ids
    ]


def compatible_provider_protocol_pairs(engine_id: str) -> list[tuple[str, str]]:
    engine = _engine(engine_id)
    supported_protocol_ids = set(engine.supported_protocol_ids)
    pairs: list[tuple[str, str]] = []
    for provider in get_llm_catalog().providers:
        if not provider.enabled:
            continue
        for binding in provider.protocol_bindings:
            if binding.protocol_id in supported_protocol_ids:
                pairs.append((provider.id, binding.protocol_id))
    return pairs


def compatible_engine_ids(provider_id: str, protocol_id: str) -> list[str]:
    validate_provider_protocol(provider_id, protocol_id)
    return [
        engine.id
        for engine in get_llm_catalog().engines
        if engine.enabled and protocol_id in engine.supported_protocol_ids
    ]


def validate_provider_protocol(provider_id: str, protocol_id: str) -> ProviderProtocolBinding:
    _validate_protocol_id(protocol_id)
    provider = _provider(provider_id)
    for binding in provider.protocol_bindings:
        if binding.protocol_id == protocol_id:
            return binding
    raise LlmCompatibilityError(
        code="LLM_PROVIDER_PROTOCOL_UNSUPPORTED",
        message=f"Provider '{provider_id}' does not implement protocol '{protocol_id}'",
        data={"provider": provider_id, "protocol": protocol_id},
        user_action="fix_input",
    )


def validate_engine_protocol(engine_id: str, protocol_id: str) -> None:
    _validate_protocol_id(protocol_id)
    engine = _engine(engine_id)
    if protocol_id not in engine.supported_protocol_ids:
        raise LlmCompatibilityError(
            code="LLM_PROTOCOL_NOT_SUPPORTED_BY_ENGINE",
            message=f"Protocol '{protocol_id}' is not supported by engine '{engine_id}'",
            data={"engine_kind": engine_id, "protocol": protocol_id},
            user_action="fix_input",
        )


def validate_secret_for_engine(
    engine_id: str,
    kind: str,
    provider_id: str | None,
    protocol_id: str | None,
) -> ProviderProtocolBinding:
    if kind != CredentialKind.MODEL.value or not provider_id or not protocol_id:
        raise LlmCompatibilityError(
            code="LLM_SECRET_IDENTITY_INVALID",
            message="Agent model configuration must be a model credential with Provider and Protocol",
            data={
                "engine_kind": engine_id,
                "kind": kind,
                "provider": provider_id,
                "protocol": protocol_id,
            },
            user_action="fix_input",
        )
    binding = validate_provider_protocol(provider_id, protocol_id)
    validate_engine_protocol(engine_id, protocol_id)
    return binding


def validate_credential_data(provider_id: str, protocol_id: str, data: Mapping[str, str]) -> None:
    binding = validate_provider_protocol(provider_id, protocol_id)
    profile = get_llm_catalog().credential_profile(binding.credential_profile_id)

    missing_required = [
        field.key
        for field in profile.fields
        if field.required and not str(data.get(field.key, "")).strip()
    ]
    if missing_required:
        raise LlmCompatibilityError(
            code="LLM_SECRET_CREDENTIALS_INCOMPLETE",
            message="Required LLM credential fields are missing",
            data={
                "provider": provider_id,
                "protocol": protocol_id,
                "required_fields": missing_required,
            },
            user_action="fix_input",
        )

    missing_groups = [
        group
        for group in profile.required_any_of
        if not any(str(data.get(key, "")).strip() for key in group)
    ]
    if missing_groups:
        raise LlmCompatibilityError(
            code="LLM_SECRET_CREDENTIALS_INCOMPLETE",
            message="At least one credential from each required group must be provided",
            data={
                "provider": provider_id,
                "protocol": protocol_id,
                "required_any_of": missing_groups,
            },
            user_action="fix_input",
        )


def resolve_credential_profile(secret) -> CredentialProfile | None:
    """Resolve the LLM credential profile for a secret, or ``None``.

    Returns ``None`` for non-LLM secrets, secrets missing provider/protocol, and
    provider/protocol pairs no longer known to the catalog (e.g. legacy data
    predating a compatibility guard). Read paths degrade to an unresolved model
    instead of propagating the error.
    """
    if (
        getattr(secret, "kind", None) != CredentialKind.MODEL.value
        or not getattr(secret, "provider", None)
        or not getattr(secret, "protocol", None)
    ):
        return None
    try:
        binding = validate_provider_protocol(secret.provider, secret.protocol)
        return get_llm_catalog().credential_profile(binding.credential_profile_id)
    except (LlmCompatibilityError, LlmCatalogError) as exc:
        logger.warning(
            "Skipping model resolution for secret %r: incompatible provider/protocol "
            "(provider=%r, protocol=%r): %s",
            getattr(secret, "name", None),
            getattr(secret, "provider", None),
            getattr(secret, "protocol", None),
            exc,
        )
        return None
