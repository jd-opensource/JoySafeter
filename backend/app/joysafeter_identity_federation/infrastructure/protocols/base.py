from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pydantic import BaseModel

from ...domain.errors import ConfigurationIssue, FederationConfigurationError
from ...domain.models import ProtocolId, ProviderProtocolSettings
from ...domain.ports import ProtocolAdapter


@dataclass(frozen=True, slots=True)
class ProtocolDefinition:
    protocol_id: ProtocolId
    schema_type: type[BaseModel]
    to_domain_settings: Callable[[BaseModel], ProviderProtocolSettings]


def _unknown_protocol_error(protocol_id: ProtocolId | str) -> FederationConfigurationError:
    return FederationConfigurationError(
        [
            ConfigurationIssue(
                provider_id=str(protocol_id),
                field="protocol",
                code="FEDERATION_PROTOCOL_UNKNOWN",
                message=f"Protocol {protocol_id!r} is not registered",
            )
        ]
    )


class ProtocolSchemaRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ProtocolDefinition] = {}

    def register(self, definition: ProtocolDefinition) -> None:
        protocol_key = str(definition.protocol_id)
        if protocol_key in self._definitions:
            raise RuntimeError(f"Protocol {protocol_key!r} is already registered")
        self._definitions[protocol_key] = definition

    def require(self, protocol_id: ProtocolId | str) -> ProtocolDefinition:
        try:
            return self._definitions[str(protocol_id)]
        except KeyError as error:
            raise _unknown_protocol_error(protocol_id) from error

    def validate_configuration(
        self,
        protocol_id: ProtocolId | str,
        configuration: Mapping[str, object],
    ) -> ProviderProtocolSettings:
        definition = self.require(protocol_id)
        return definition.to_domain_settings(definition.schema_type.model_validate(configuration))


class ProtocolAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ProtocolAdapter] = {}

    def register(self, adapter: ProtocolAdapter) -> None:
        protocol_key = str(adapter.protocol_id)
        if protocol_key in self._adapters:
            raise RuntimeError(f"Protocol {protocol_key!r} is already registered")
        self._adapters[protocol_key] = adapter

    def require(self, protocol_id: ProtocolId | str) -> ProtocolAdapter:
        try:
            return self._adapters[str(protocol_id)]
        except KeyError as error:
            raise _unknown_protocol_error(protocol_id) from error
