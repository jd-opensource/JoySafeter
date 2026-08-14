from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class LlmCatalogError(ValueError):
    pass


class _CatalogItem(Protocol):
    id: str


_CatalogItemT = TypeVar("_CatalogItemT", bound=_CatalogItem)


class CredentialField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    type: Literal["secret", "text", "url", "select"]
    required: bool = False
    placeholder: str | None = None
    help_text: str | None = None
    options: list[str] = Field(default_factory=list)
    advanced: bool = False


class CredentialProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    fields: list[CredentialField]
    required_any_of: list[list[str]] = Field(default_factory=list)
    base_url_key: str | None = None
    model_key: str | None = None

    @model_validator(mode="after")
    def validate_field_references(self) -> CredentialProfile:
        field_keys = [field.key for field in self.fields]
        duplicate_keys = _duplicate_ids(field_keys)
        if duplicate_keys:
            raise ValueError(f"duplicate credential field key: {duplicate_keys[0]}")
        known_fields = set(field_keys)
        for key_name, key in (("base_url_key", self.base_url_key), ("model_key", self.model_key)):
            if key is not None and key not in known_fields:
                raise ValueError(f"{key_name} references unknown field: {key}")
        for group in self.required_any_of:
            if not group:
                raise ValueError("required_any_of group must not be empty")
            for key in group:
                if key not in known_fields:
                    raise ValueError(f"required_any_of references unknown field: {key}")
        return self


class ProviderProtocolBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_id: str
    credential_profile_id: str
    default_base_url: str | None = None
    model_suggestions: list[str] = Field(default_factory=list)


class EngineCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    enabled: bool = True
    supported_protocol_ids: list[str]
    preferred_protocol_ids: list[str] = Field(default_factory=list)


class ProtocolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    description: str


class ProviderDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    display_name: str
    enabled: bool = True
    protocol_bindings: list[ProviderProtocolBinding]


class LlmCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    engines: list[EngineCapability]
    protocols: list[ProtocolDefinition]
    providers: list[ProviderDefinition]
    credential_profiles: list[CredentialProfile]

    @model_validator(mode="after")
    def validate_references(self) -> LlmCatalog:
        _ensure_unique_ids("engine", [engine.id for engine in self.engines])
        _ensure_unique_ids("protocol", [protocol.id for protocol in self.protocols])
        _ensure_unique_ids("provider", [provider.id for provider in self.providers])
        _ensure_unique_ids("credential profile", [profile.id for profile in self.credential_profiles])

        overlapping_engine_provider_ids = {engine.id for engine in self.engines} & {
            provider.id for provider in self.providers
        }
        if overlapping_engine_provider_ids:
            raise ValueError(
                "engine and provider ids overlap: "
                f"{sorted(overlapping_engine_provider_ids)[0]}"
            )

        protocol_ids = {protocol.id for protocol in self.protocols}
        profile_ids = {profile.id for profile in self.credential_profiles}
        for engine in self.engines:
            for protocol_id in engine.supported_protocol_ids:
                if protocol_id not in protocol_ids:
                    raise ValueError(f"engine '{engine.id}' references unknown protocol: {protocol_id}")
            unsupported_preferred = set(engine.preferred_protocol_ids) - set(engine.supported_protocol_ids)
            if unsupported_preferred:
                raise ValueError(
                    f"engine '{engine.id}' preferred protocol is not supported: {sorted(unsupported_preferred)[0]}"
                )

        for provider in self.providers:
            binding_protocol_ids = [binding.protocol_id for binding in provider.protocol_bindings]
            duplicate_bindings = _duplicate_ids(binding_protocol_ids)
            if duplicate_bindings:
                raise ValueError(
                    f"provider '{provider.id}' has duplicate protocol binding: {duplicate_bindings[0]}"
                )
            for binding in provider.protocol_bindings:
                if binding.protocol_id not in protocol_ids:
                    raise ValueError(
                        f"provider '{provider.id}' references unknown protocol: {binding.protocol_id}"
                    )
                if binding.credential_profile_id not in profile_ids:
                    raise ValueError(
                        "provider "
                        f"'{provider.id}' references unknown credential profile: {binding.credential_profile_id}"
                    )
        return self

    def engine(self, engine_id: str) -> EngineCapability:
        return self._lookup("engine", engine_id, self.engines)

    def protocol(self, protocol_id: str) -> ProtocolDefinition:
        return self._lookup("protocol", protocol_id, self.protocols)

    def provider(self, provider_id: str) -> ProviderDefinition:
        return self._lookup("provider", provider_id, self.providers)

    def credential_profile(self, profile_id: str) -> CredentialProfile:
        return self._lookup("credential profile", profile_id, self.credential_profiles)

    @staticmethod
    def _lookup(kind: str, item_id: str, items: list[_CatalogItemT]) -> _CatalogItemT:
        for item in items:
            if item.id == item_id:
                return item
        raise LlmCatalogError(f"unknown {kind}: {item_id}")


def _duplicate_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for item_id in ids:
        if item_id in seen and item_id not in duplicates:
            duplicates.append(item_id)
        seen.add(item_id)
    return duplicates


def _ensure_unique_ids(kind: str, ids: list[str]) -> None:
    duplicates = _duplicate_ids(ids)
    if duplicates:
        raise ValueError(f"duplicate {kind} id: {duplicates[0]}")


def load_llm_catalog(path: Path) -> LlmCatalog:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise LlmCatalogError("LLM catalog root must be an object")
        return LlmCatalog.model_validate(raw)
    except LlmCatalogError:
        raise
    except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
        raise LlmCatalogError(str(exc)) from exc


@lru_cache(maxsize=1)
def get_llm_catalog() -> LlmCatalog:
    catalog_path = Path(__file__).resolve().parents[3] / "config" / "llm_catalog.yaml"
    return load_llm_catalog(catalog_path)
