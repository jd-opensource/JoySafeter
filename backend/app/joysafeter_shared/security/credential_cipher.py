import base64
import binascii
import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_AES_KEY_SIZE = 32
_NONCE_SIZE = 12
_TAG_SIZE = 16
_ENCRYPTED_PREFIX = "enc:v1:"
_KEY_REQUIRED_MESSAGE = "JOYSAFETER_VAULT_ENCRYPTION_KEY is required for credential encryption"


class CredentialCipherConfigurationError(ValueError):
    pass


class CredentialCiphertextError(ValueError):
    pass


class CredentialCipher:
    """AES-256-GCM storage boundary for all managed credential material."""

    def __init__(self, key_str: Optional[str] = None):
        self._key: Optional[bytes] = None
        self._configuration_error = _KEY_REQUIRED_MESSAGE
        if key_str:
            self._load_key(key_str)

    def _load_key(self, key_str: str) -> None:
        key_str = key_str.strip()
        try:
            if len(key_str) == _AES_KEY_SIZE * 2:
                key_bytes = bytes.fromhex(key_str)
            else:
                key_bytes = base64.b64decode(key_str, validate=True)
        except (ValueError, binascii.Error):
            self._configuration_error = (
                "JOYSAFETER_VAULT_ENCRYPTION_KEY must be a 32-byte hex or base64 value"
            )
            return

        if len(key_bytes) != _AES_KEY_SIZE:
            self._configuration_error = (
                f"JOYSAFETER_VAULT_ENCRYPTION_KEY must decode to {_AES_KEY_SIZE} bytes"
            )
            return

        self._key = key_bytes
        self._configuration_error = ""

    def require_enabled(self) -> None:
        if self._key is None:
            raise CredentialCipherConfigurationError(self._configuration_error)

    def encrypt(self, plaintext: str) -> str:
        self.require_enabled()
        assert self._key is not None

        nonce = secrets.token_bytes(_NONCE_SIZE)
        ciphertext = AESGCM(self._key).encrypt(nonce, plaintext.encode("utf-8"), None)
        return _ENCRYPTED_PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt_stored(self, stored: str) -> str:
        self.require_enabled()
        if not stored.startswith(_ENCRYPTED_PREFIX):
            raise CredentialCiphertextError("Stored credential is not encrypted")

        try:
            raw = base64.b64decode(stored[len(_ENCRYPTED_PREFIX) :], validate=True)
            if len(raw) < _NONCE_SIZE + _TAG_SIZE:
                raise ValueError("ciphertext payload is too short")
            nonce = raw[:_NONCE_SIZE]
            ciphertext = raw[_NONCE_SIZE:]
            assert self._key is not None
            plaintext = AESGCM(self._key).decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise CredentialCiphertextError("Failed to decrypt stored credential") from exc

    @staticmethod
    def generate_key() -> str:
        return base64.b64encode(secrets.token_bytes(_AES_KEY_SIZE)).decode("ascii")
