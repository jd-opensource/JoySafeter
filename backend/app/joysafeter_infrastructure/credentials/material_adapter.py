from __future__ import annotations

from collections.abc import Mapping

from app.joysafeter_application.credentials.binding_service import (
    BindingIssuanceAuthority,
    ResolvedCredentialMaterial,
    ValidatedCredentialBinding,
)
from app.joysafeter_application.credentials.ports import EncryptedCredentialMaterialRepositoryPort
from app.joysafeter_domain.credentials.material import (
    CredentialMaterial,
    _issue_material_reveal_capability,
)
from app.joysafeter_domain.credentials.types import CredentialFieldName
from app.joysafeter_infrastructure.sensitive_material.versioned import VersionedMaterialProtector


class ManagedCredentialMaterialAdapter:
    def __init__(
        self,
        repository: EncryptedCredentialMaterialRepositoryPort | None,
        protector: VersionedMaterialProtector,
        issuance_authority: BindingIssuanceAuthority,
    ) -> None:
        if type(issuance_authority) is not BindingIssuanceAuthority:
            raise TypeError("ManagedCredentialMaterialAdapter requires BindingIssuanceAuthority")
        self._repository = repository
        self._protector = protector
        self._issuance_authority = issuance_authority

    def bind_repository(self, repository: EncryptedCredentialMaterialRepositoryPort) -> None:
        if self._repository is not None:
            raise RuntimeError("managed credential material repository is already bound")
        self._repository = repository

    async def load(self, binding: ValidatedCredentialBinding) -> ResolvedCredentialMaterial:
        self._issuance_authority.validate(binding)
        if self._repository is None:
            raise RuntimeError("managed credential material repository is not bound")
        encrypted = await self._repository.load_encrypted_material(
            binding.binding.credential_id,
            binding.binding.project_id,
        )
        if binding.requests_all_fields:
            selected = encrypted.items()
        else:
            selected = ((name, encrypted[str(name)]) for name in binding.authorized_fields if str(name) in encrypted)
        resolved = {CredentialFieldName(str(name)): self._protector.reveal(value) for name, value in selected}
        missing = binding.authorized_fields - set(resolved)
        if missing:
            raise KeyError(f"credential material fields are missing: {sorted(missing)!r}")
        return ResolvedCredentialMaterial(resolved)

    def protect(self, material: CredentialMaterial) -> dict[str, str]:
        capability = _issue_material_reveal_capability()
        return {str(name): self._protector.protect(value.reveal(capability)) for name, value in material.fields.items()}

    def protect_values(self, values: Mapping[str, str] | None) -> dict[str, str]:
        return {str(name): self._protector.protect(value) for name, value in (values or {}).items()}

    def reveal_values(self, values: Mapping[str, str] | None) -> dict[str, str]:
        return {str(name): self._protector.reveal(value) for name, value in (values or {}).items()}
