from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from app.joysafeter_domain.credentials.bindings import (
    CredentialBinding,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpGroupBinding,
    ModelCatalogContext,
    ModelInferenceBinding,
    WebhookAuthBinding,
)
from app.joysafeter_domain.credentials.policies import validate_credential_binding
from app.joysafeter_domain.credentials.types import CredentialFieldName

from .ports import CredentialRepositoryPort


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


class CredentialBindingService:
    def __init__(self, credentials: CredentialRepositoryPort) -> None:
        self._credentials = credentials

    async def validate(
        self,
        binding: CredentialBinding,
        *,
        requested_fields: frozenset[CredentialFieldName] | None = None,
        catalog_context: ModelCatalogContext | None = None,
    ) -> ValidatedCredentialBinding:
        if isinstance(binding, McpGroupBinding):
            raise TypeError("MCP Group bindings are validated by CredentialGroupService")
        resource = await self._credentials.get_resource(binding.credential_id, binding.project_id)
        if resource is None:
            raise LookupError("credential resource was not found")
        validate_credential_binding(resource, binding, catalog_context=catalog_context)
        if isinstance(binding, EnvironmentInjectionBinding):
            return ValidatedCredentialBinding.all_fields(binding)
        if isinstance(binding, WebhookAuthBinding):
            return ValidatedCredentialBinding(binding, frozenset({binding.credential_field}))
        if isinstance(binding, HttpEgressBinding):
            return ValidatedCredentialBinding(binding, frozenset({binding.inject.credential_field}))
        if isinstance(binding, ModelInferenceBinding):
            if not requested_fields:
                raise ValueError("model inference must explicitly authorize material fields")
            missing = requested_fields - resource.material.field_names
            if missing:
                raise ValueError(f"credential material fields are missing: {sorted(missing)!r}")
            return ValidatedCredentialBinding(binding, requested_fields)
        raise TypeError(f"unsupported credential binding: {type(binding).__name__}")
