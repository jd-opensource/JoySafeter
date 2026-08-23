from __future__ import annotations

from app.joysafeter_domain.credentials.bindings import (
    CredentialBinding,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    ModelCatalogContext,
    ModelInferenceBinding,
    WebhookAuthBinding,
)
from app.joysafeter_domain.credentials.policies import CredentialPolicyError
from app.joysafeter_domain.credentials.types import CredentialFieldName
from app.joysafeter_domain.llm.model_inference_policy import ModelInferencePolicyError
from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipherConfigurationError,
    CredentialCiphertextError,
)

from .binding_service import (
    CredentialBindingService,
    ModelInferenceResolution,
    ResolvedCredentialMaterial,
    ValidatedCredentialBinding,
)
from .ports import (
    CredentialAccessAuditEntry,
    CredentialAccessAuditPort,
    CredentialAccessContext,
    CredentialAccessResult,
    CredentialMaterialPort,
)

MaterialCredentialBinding = ModelInferenceBinding | WebhookAuthBinding | EnvironmentInjectionBinding | HttpEgressBinding


class CredentialMaterialAccessService:
    def __init__(
        self,
        bindings: CredentialBindingService,
        material: CredentialMaterialPort,
        audit: CredentialAccessAuditPort,
    ) -> None:
        self._bindings = bindings
        self._material = material
        self._audit = audit

    async def resolve(
        self,
        binding: WebhookAuthBinding | EnvironmentInjectionBinding | HttpEgressBinding,
        *,
        context: CredentialAccessContext,
        catalog_context: ModelCatalogContext | None = None,
    ) -> ResolvedCredentialMaterial:
        try:
            validated = await self._bindings.validate(binding, catalog_context=catalog_context)
        except Exception as exc:
            await self._append(
                binding,
                context=context,
                field_names=(),
                result=CredentialAccessResult.DENIED,
                error_code=_validation_error_code(exc),
            )
            raise
        return await self._load(validated, context=context)

    async def resolve_model_inference(
        self,
        binding: ModelInferenceBinding,
        *,
        context: CredentialAccessContext,
    ) -> tuple[ResolvedCredentialMaterial, ModelInferenceResolution]:
        try:
            validated, resolution = await self._bindings.validate_model_inference(binding)
        except Exception as exc:
            await self._append(
                binding,
                context=context,
                field_names=(),
                result=CredentialAccessResult.DENIED,
                error_code=_validation_error_code(exc),
            )
            raise
        return await self._load(validated, context=context), resolution

    async def _load(
        self,
        validated: ValidatedCredentialBinding,
        *,
        context: CredentialAccessContext,
    ) -> ResolvedCredentialMaterial:
        binding = validated.binding
        try:
            material = await self._material.load(validated)
        except Exception as exc:
            await self._append(
                binding,
                context=context,
                field_names=tuple(validated.authorized_fields),
                result=CredentialAccessResult.FAILED,
                error_code=_material_error_code(exc),
            )
            raise
        await self._append(
            binding,
            context=context,
            field_names=tuple(material.fields),
            result=CredentialAccessResult.SUCCESS,
            error_code=None,
        )
        return material

    async def _append(
        self,
        binding: MaterialCredentialBinding,
        *,
        context: CredentialAccessContext,
        field_names: tuple[CredentialFieldName, ...],
        result: CredentialAccessResult,
        error_code: str | None,
    ) -> None:
        await self._audit.append(
            CredentialAccessAuditEntry(
                project_id=binding.project_id,
                credential_id=binding.credential_id,
                credential_kind=_credential_kind(binding),
                usage=binding.usage,
                consumer_type=context.consumer_type,
                consumer_id=context.consumer_id,
                actor=context.actor,
                session_id=context.session_id,
                task_id=context.task_id,
                generation=context.generation,
                field_names=field_names,
                result=result,
                error_code=error_code,
            )
        )


def _credential_kind(binding: CredentialBinding) -> str:
    return "model" if isinstance(binding, ModelInferenceBinding) else "service"


def _validation_error_code(exc: Exception) -> str:
    if isinstance(exc, CredentialPolicyError):
        return f"policy_{exc.code.value}"
    if isinstance(exc, ModelInferencePolicyError):
        return f"policy_{exc.code.value}"
    if isinstance(exc, LookupError):
        return "credential_not_found"
    return "binding_validation_failed"


def _material_error_code(exc: Exception) -> str:
    if isinstance(exc, CredentialCipherConfigurationError):
        return "cipher_unavailable"
    if isinstance(exc, CredentialCiphertextError):
        return "ciphertext_invalid"
    if isinstance(exc, KeyError):
        return "material_field_missing"
    if isinstance(exc, LookupError):
        return "credential_not_found_after_validation"
    return "material_load_failed"
