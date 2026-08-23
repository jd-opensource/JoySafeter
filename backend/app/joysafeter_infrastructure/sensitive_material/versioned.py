from __future__ import annotations

from app.joysafeter_shared.security.credential_cipher import CredentialCipher


class VersionedMaterialProtector:
    def __init__(
        self,
        legacy_key: str | None,
        *,
        keyring_json: str | None = None,
        write_key_id: str | None = None,
    ) -> None:
        self._cipher = CredentialCipher(
            legacy_key,
            keyring_json=keyring_json,
            write_key_id=write_key_id,
        )

    def require_enabled(self) -> None:
        self._cipher.require_enabled()

    @property
    def active_envelope_prefix(self) -> str:
        return self._cipher.active_envelope_prefix

    def protect(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("material value must be a string")
        return self._cipher.encrypt(value)

    def reveal(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("stored material value must be a string")
        return self._cipher.decrypt_stored(value)

    def normalize(self, value: str) -> str:
        if not isinstance(value, str):
            raise TypeError("stored material value must be a string")
        return self._cipher.normalize_stored(value)
