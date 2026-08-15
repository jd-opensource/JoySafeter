from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from ..domain.errors import FederationError
from ..domain.models import ActiveProvider, FederationSettings, ProviderDescriptor, ProviderId


@dataclass(frozen=True, slots=True, init=False)
class ProviderRegistry:
    _providers: Mapping[ProviderId, ActiveProvider] = field(repr=False)
    settings: FederationSettings

    def __init__(self, providers: Iterable[ActiveProvider], settings: FederationSettings) -> None:
        copied: dict[ProviderId, ActiveProvider] = {}
        for provider in providers:
            if provider.id in copied:
                raise RuntimeError(f"Provider {provider.id.value!r} is already registered")
            copied[provider.id] = provider
        object.__setattr__(self, "_providers", MappingProxyType(copied))
        object.__setattr__(self, "settings", settings)

    @property
    def providers(self) -> Mapping[ProviderId, ActiveProvider]:
        return self._providers

    def require(self, provider_id: ProviderId) -> ActiveProvider:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise FederationError(
                code="FEDERATION_PROVIDER_NOT_ACTIVE",
                message=f"Provider {provider_id.value!r} is not active",
            ) from error

    def list_public(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(
            ProviderDescriptor(id=provider.id, display_name=provider.display_name, icon=provider.icon)
            for provider in self._providers.values()
        )
