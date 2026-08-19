from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.joysafeter_domain.credentials.bindings import (
    CredentialBinding,
    EngineKind,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpGroupBinding,
    ModelCatalogContext,
    ModelInferenceBinding,
    WebhookAuthBinding,
)
from app.joysafeter_domain.credentials.policies import (
    CredentialPolicyError,
    validate_credential_binding,
)
from app.joysafeter_domain.credentials.resource import CredentialResource
from app.joysafeter_domain.credentials.types import CredentialFieldName
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.model_inference_policy import (
    ModelInferenceMaterialFieldMissingError,
    require_enabled_model_inference_engine,
)

from .ports import CredentialRepositoryPort


class BindingIssuanceAuthority:
    __slots__ = ("__bindings",)

    def __init__(self) -> None:
        self.__bindings: dict[
            int,
            tuple[ValidatedCredentialBinding, tuple[object, ...]],
        ] = {}

    @staticmethod
    def __snapshot(binding: ValidatedCredentialBinding) -> tuple[object, ...]:
        return (
            type(binding),
            type(binding.binding),
            repr(binding.binding),
            binding.authorized_fields,
            binding.requests_all_fields,
        )

    def validate(self, binding: ValidatedCredentialBinding) -> None:
        record = self.__bindings.get(id(binding))
        if record is None or record[0] is not binding:
            raise TypeError("validated credential binding was not issued by this composition")
        if record[1] != self.__snapshot(binding):
            raise TypeError("issued validated credential binding was mutated after validation")


@dataclass(frozen=True, slots=True)
class ValidatedCredentialBinding:
    binding: CredentialBinding
    authorized_fields: frozenset[CredentialFieldName] = field(default_factory=frozenset)
    requests_all_fields: bool = False

    def __post_init__(self) -> None:
        fields = frozenset(
            value if isinstance(value, CredentialFieldName) else CredentialFieldName(value)
            for value in self.authorized_fields
        )
        if self.requests_all_fields and not isinstance(self.binding, EnvironmentInjectionBinding):
            raise ValueError("Environment Injection is the only binding allowed to request all fields")
        if isinstance(self.binding, ModelInferenceBinding):
            raise TypeError("ModelInferenceBinding requires dedicated model inference validation")
        if self.requests_all_fields and fields:
            raise ValueError("all-fields bindings must not also enumerate authorized fields")
        if not self.requests_all_fields and not fields:
            raise ValueError("validated bindings must authorize at least one field")
        object.__setattr__(self, "authorized_fields", fields)

    @classmethod
    def all_fields(cls, binding: CredentialBinding) -> ValidatedCredentialBinding:
        return cls(binding=binding, requests_all_fields=True)


@dataclass(frozen=True, slots=True)
class ResolvedCredentialMaterial:
    fields: Mapping[CredentialFieldName, str] = field(repr=False)

    def __post_init__(self) -> None:
        copied: dict[CredentialFieldName, str] = {}
        for raw_name, value in self.fields.items():
            name = raw_name if isinstance(raw_name, CredentialFieldName) else CredentialFieldName(raw_name)
            if not isinstance(value, str):
                raise TypeError("resolved credential material values must be strings")
            copied[name] = value
        object.__setattr__(self, "fields", MappingProxyType(copied))

    def __repr__(self) -> str:
        return f"ResolvedCredentialMaterial(field_names={sorted(self.fields)!r}, values=<redacted>)"


@dataclass(frozen=True, slots=True)
class ModelInferenceResolution:
    provider_id: str
    protocol_id: str
    credential_profile_id: str
    base_url_key: str | None
    model_key: str | None
    default_base_url: str | None


@dataclass(frozen=True, slots=True)
class _ModelInferenceCandidate:
    context: ModelCatalogContext
    resolution: ModelInferenceResolution
    authorized_fields: frozenset[CredentialFieldName]
    required_fields: frozenset[CredentialFieldName]
    required_any_of: tuple[frozenset[CredentialFieldName], ...]


class CredentialBindingService:
    def __init__(
        self,
        credentials: CredentialRepositoryPort,
        issuance_authority: BindingIssuanceAuthority,
    ) -> None:
        if type(issuance_authority) is not BindingIssuanceAuthority:
            raise TypeError("CredentialBindingService requires BindingIssuanceAuthority")
        self._credentials = credentials
        self._issuance_authority = issuance_authority
        self._catalog = get_llm_catalog()

    async def validate(
        self,
        binding: CredentialBinding,
        *,
        catalog_context: ModelCatalogContext | None = None,
    ) -> ValidatedCredentialBinding:
        if isinstance(binding, McpGroupBinding):
            raise TypeError("MCP Group bindings are validated by CredentialGroupService")
        if isinstance(binding, ModelInferenceBinding):
            raise TypeError("ModelInferenceBinding requires dedicated model inference validation")
        await self.validate_reference(binding, catalog_context=catalog_context)
        if isinstance(binding, EnvironmentInjectionBinding):
            validated = ValidatedCredentialBinding.all_fields(binding)
            bindings = self._issuance_authority._BindingIssuanceAuthority__bindings
            snapshot = self._issuance_authority._BindingIssuanceAuthority__snapshot(validated)
            bindings[id(validated)] = (validated, snapshot)
            return validated
        if isinstance(binding, WebhookAuthBinding):
            validated = ValidatedCredentialBinding(binding, frozenset({binding.credential_field}))
            bindings = self._issuance_authority._BindingIssuanceAuthority__bindings
            snapshot = self._issuance_authority._BindingIssuanceAuthority__snapshot(validated)
            bindings[id(validated)] = (validated, snapshot)
            return validated
        if isinstance(binding, HttpEgressBinding):
            validated = ValidatedCredentialBinding(binding, frozenset({binding.inject.credential_field}))
            bindings = self._issuance_authority._BindingIssuanceAuthority__bindings
            snapshot = self._issuance_authority._BindingIssuanceAuthority__snapshot(validated)
            bindings[id(validated)] = (validated, snapshot)
            return validated
        raise TypeError(f"unsupported credential binding: {type(binding).__name__}")

    async def validate_reference(
        self,
        binding: CredentialBinding,
        *,
        catalog_context: ModelCatalogContext | None = None,
    ):
        if isinstance(binding, McpGroupBinding):
            raise TypeError("MCP Group bindings are validated by CredentialGroupService")
        if isinstance(binding, ModelInferenceBinding):
            raise TypeError("ModelInferenceBinding requires dedicated model inference validation")
        resource = await self._credentials.get_resource(binding.credential_id, binding.project_id)
        if resource is None:
            raise LookupError("credential resource was not found")
        validate_credential_binding(resource, binding, catalog_context=catalog_context)
        return resource

    def _model_inference_candidates(
        self,
        binding: ModelInferenceBinding,
    ) -> tuple[_ModelInferenceCandidate, ...]:
        engine = require_enabled_model_inference_engine(self._catalog, binding.engine_kind)
        supported_protocols = set(engine.supported_protocol_ids)
        candidates: list[_ModelInferenceCandidate] = []
        for provider in self._catalog.providers:
            if not provider.enabled:
                continue
            for provider_binding in provider.protocol_bindings:
                if provider_binding.protocol_id not in supported_protocols:
                    continue
                profile = self._catalog.credential_profile(provider_binding.credential_profile_id)
                authorized_fields = frozenset(CredentialFieldName(field.key) for field in profile.fields)
                candidates.append(
                    _ModelInferenceCandidate(
                        context=ModelCatalogContext(
                            provider_id=provider.id,
                            protocol_id=provider_binding.protocol_id,
                            engine_kind=binding.engine_kind,
                            model_ids=None,
                        ),
                        resolution=ModelInferenceResolution(
                            provider_id=provider.id,
                            protocol_id=provider_binding.protocol_id,
                            credential_profile_id=profile.id,
                            base_url_key=profile.base_url_key,
                            model_key=profile.model_key,
                            default_base_url=provider_binding.default_base_url,
                        ),
                        authorized_fields=authorized_fields,
                        required_fields=frozenset(
                            CredentialFieldName(field.key) for field in profile.fields if field.required
                        ),
                        required_any_of=tuple(
                            frozenset(CredentialFieldName(name) for name in group) for group in profile.required_any_of
                        ),
                    )
                )
        return tuple(candidates)

    async def _match_model_inference(
        self,
        binding: ModelInferenceBinding,
    ) -> tuple[CredentialResource, _ModelInferenceCandidate]:
        if type(binding) is not ModelInferenceBinding:
            raise TypeError("dedicated model inference validation requires ModelInferenceBinding")
        if not isinstance(binding.engine_kind, EngineKind):
            raise TypeError("model inference engine kind must be an EngineKind")
        candidates = self._model_inference_candidates(binding)
        resource = await self._credentials.get_resource(
            binding.credential_id,
            binding.project_id,
        )
        if resource is None:
            raise LookupError("credential resource was not found")
        last_error: CredentialPolicyError | None = None
        for candidate in candidates:
            try:
                validate_credential_binding(
                    resource,
                    binding,
                    catalog_context=candidate.context,
                )
            except CredentialPolicyError as exc:
                last_error = exc
                continue
            return resource, candidate
        if last_error is not None:
            raise last_error
        raise ValueError("model inference Catalog has no compatible providers")

    async def validate_model_inference_reference(
        self,
        binding: ModelInferenceBinding,
    ) -> ModelInferenceResolution:
        _resource, candidate = await self._match_model_inference(binding)
        return candidate.resolution

    async def validate_model_inference(
        self,
        binding: ModelInferenceBinding,
    ) -> tuple[ValidatedCredentialBinding, ModelInferenceResolution]:
        resource, candidate = await self._match_model_inference(binding)
        present_fields = resource.material.field_names
        authorized_fields = candidate.authorized_fields & present_fields
        missing_required_fields = candidate.required_fields - present_fields
        missing_required_any_of = tuple(
            group for group in candidate.required_any_of if not group.intersection(present_fields)
        )
        if missing_required_fields or missing_required_any_of or not authorized_fields:
            raise ModelInferenceMaterialFieldMissingError(
                provider_id=candidate.resolution.provider_id,
                protocol_id=candidate.resolution.protocol_id,
                missing_required_fields=missing_required_fields,
                missing_required_any_of=missing_required_any_of,
            )
        validated = object.__new__(ValidatedCredentialBinding)
        object.__setattr__(validated, "binding", binding)
        object.__setattr__(validated, "authorized_fields", authorized_fields)
        object.__setattr__(validated, "requests_all_fields", False)
        bindings = self._issuance_authority._BindingIssuanceAuthority__bindings
        snapshot = self._issuance_authority._BindingIssuanceAuthority__snapshot(validated)
        bindings[id(validated)] = (validated, snapshot)
        return validated, candidate.resolution
