from __future__ import annotations

from enum import StrEnum

from app.joysafeter_domain.credentials.bindings import EngineKind, ModelInferenceBinding
from app.joysafeter_domain.credentials.policies import (
    CredentialPolicyError,
    CredentialPolicyErrorCode,
)
from app.joysafeter_domain.credentials.types import (
    CredentialFieldName,
    CredentialId,
    ProjectId,
    require_project_id,
)

from .catalog import EngineCapability, LlmCatalog


class ModelInferencePolicyErrorCode(StrEnum):
    ENGINE_DISABLED = "engine_disabled"


class ModelInferencePolicyError(ValueError):
    def __init__(
        self,
        code: ModelInferencePolicyErrorCode,
        message: str,
        *,
        engine_kind: EngineKind,
    ) -> None:
        self.code = code
        self.engine_kind = engine_kind
        super().__init__(message)


class ModelInferenceMaterialFieldMissingError(CredentialPolicyError):
    def __init__(
        self,
        *,
        provider_id: str,
        protocol_id: str,
        missing_required_fields: frozenset[CredentialFieldName],
        missing_required_any_of: tuple[frozenset[CredentialFieldName], ...],
    ) -> None:
        self.provider_id = provider_id
        self.protocol_id = protocol_id
        self.missing_required_fields = missing_required_fields
        self.missing_required_any_of = missing_required_any_of
        super().__init__(
            CredentialPolicyErrorCode.FIELD_MISSING,
            "required model credential material is missing",
        )


def require_enabled_model_inference_engine(
    catalog: LlmCatalog,
    engine_kind: EngineKind | str,
) -> EngineCapability:
    normalized_engine_kind = engine_kind if isinstance(engine_kind, EngineKind) else EngineKind(engine_kind)
    engine = catalog.engine(normalized_engine_kind.value)
    if not engine.enabled:
        raise ModelInferencePolicyError(
            ModelInferencePolicyErrorCode.ENGINE_DISABLED,
            f"LLM engine is disabled: {normalized_engine_kind.value}",
            engine_kind=normalized_engine_kind,
        )
    return engine


def build_model_inference_policy(
    catalog: LlmCatalog,
    *,
    project_id: ProjectId,
    credential_id: CredentialId,
    engine_kind: EngineKind | str,
    model_id: str | None,
) -> ModelInferenceBinding:
    normalized_engine_kind = engine_kind if isinstance(engine_kind, EngineKind) else EngineKind(engine_kind)
    require_enabled_model_inference_engine(catalog, normalized_engine_kind)
    return ModelInferenceBinding(
        project_id=require_project_id(project_id),
        credential_id=credential_id,
        engine_kind=normalized_engine_kind,
        model_id=model_id,
    )
