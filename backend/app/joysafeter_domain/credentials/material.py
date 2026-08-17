from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .types import CREDENTIAL_FIELD_NAME_MAX_LENGTH, CredentialFieldName

CREDENTIAL_MATERIAL_MAX_FIELDS = 50
CREDENTIAL_MATERIAL_MAX_FIELD_NAME_LENGTH = CREDENTIAL_FIELD_NAME_MAX_LENGTH
CREDENTIAL_MATERIAL_MAX_VALUE_LENGTH = 8192

_POSIX_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MATERIAL_REVEAL_TOKEN = object()


@dataclass(frozen=True, slots=True)
class MaterialRevealCapability:
    _token: object = field(repr=False)


def _issue_material_reveal_capability() -> MaterialRevealCapability:
    return MaterialRevealCapability(_MATERIAL_REVEAL_TOKEN)


@dataclass(frozen=True, slots=True)
class SensitiveValue:
    _value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self._value, str):
            raise TypeError("credential material value must be a string")
        if len(self._value) > CREDENTIAL_MATERIAL_MAX_VALUE_LENGTH:
            raise ValueError(
                f"credential material value must not exceed {CREDENTIAL_MATERIAL_MAX_VALUE_LENGTH} Unicode characters"
            )

    def __repr__(self) -> str:
        return "SensitiveValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def reveal(self, capability: MaterialRevealCapability) -> str:
        if not isinstance(capability, MaterialRevealCapability) or capability._token is not _MATERIAL_REVEAL_TOKEN:
            raise PermissionError("credential material reveal capability is required")
        return self._value


@dataclass(frozen=True, slots=True)
class CredentialMaterial:
    fields: Mapping[CredentialFieldName, SensitiveValue] = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.fields, Mapping):
            raise TypeError("credential material fields must be a mapping")
        if len(self.fields) > CREDENTIAL_MATERIAL_MAX_FIELDS:
            raise ValueError(f"credential material supports at most {CREDENTIAL_MATERIAL_MAX_FIELDS} fields")

        copied: dict[CredentialFieldName, SensitiveValue] = {}
        for raw_name, value in self.fields.items():
            name = raw_name if isinstance(raw_name, CredentialFieldName) else CredentialFieldName(raw_name)
            if not isinstance(value, SensitiveValue):
                raise TypeError("credential material fields must contain SensitiveValue values")
            copied[name] = value
        object.__setattr__(self, "fields", MappingProxyType(copied))

    @property
    def field_names(self) -> frozenset[CredentialFieldName]:
        return frozenset(self.fields)

    def validate_environment_field_names(self) -> None:
        invalid = sorted(name for name in self.fields if _POSIX_ENVIRONMENT_NAME.fullmatch(name) is None)
        if invalid:
            raise ValueError(f"Environment Injection requires POSIX field names: {', '.join(invalid)}")

    def __repr__(self) -> str:
        return f"CredentialMaterial(field_names={sorted(self.field_names)!r}, values=<redacted>)"
