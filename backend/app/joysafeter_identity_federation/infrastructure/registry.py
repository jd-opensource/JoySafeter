from collections.abc import Iterable, Mapping
from types import MappingProxyType

from ..domain.errors import ConfigurationIssue, FederationConfigurationError
from ..domain.models import ActiveProvider, FederationSettings, ProviderDescriptor, ProviderId


class ProviderRegistry:
    def __init__(self, providers: Iterable[ActiveProvider], settings: FederationSettings) -> None:
        copied: dict[ProviderId, ActiveProvider] = {}
        for provider in providers:
            if provider.id in copied:
                raise RuntimeError(f"Provider {provider.id.value!r} is already registered")
            copied[provider.id] = provider
        self._providers = MappingProxyType(copied)
        self.settings = settings

    @property
    def providers(self) -> Mapping[ProviderId, ActiveProvider]:
        return self._providers

    def require(self, provider_id: ProviderId) -> ActiveProvider:
        try:
            return self._providers[provider_id]
        except KeyError as error:
            raise FederationConfigurationError(
                [
                    ConfigurationIssue(
                        provider_id=provider_id.value,
                        field="provider",
                        code="FEDERATION_PROVIDER_UNKNOWN",
                        message=f"Provider {provider_id.value!r} is not active",
                    )
                ]
            ) from error

    def list_public(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(
            ProviderDescriptor(id=provider.id, display_name=provider.display_name, icon=provider.icon)
            for provider in self._providers.values()
        )
