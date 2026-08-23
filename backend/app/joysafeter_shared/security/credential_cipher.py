import base64
import binascii
import json
import re
import secrets
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_AES_KEY_SIZE = 32
_NONCE_SIZE = 12
_TAG_SIZE = 16
_V1_ENCRYPTED_PREFIX = "enc:v1:"
_V2_ENCRYPTED_PREFIX = "enc:v2:"
_LEGACY_ENCRYPTED_PREFIX = "enc:"
_KEY_REQUIRED_MESSAGE = "JOYSAFETER_VAULT_ENCRYPTION_KEY is required for credential encryption"
_KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class CredentialCipherConfigurationError(ValueError):
    pass


class CredentialCiphertextError(ValueError):
    pass


class CredentialCipher:
    """AES-256-GCM storage boundary for all managed credential material."""

    def __init__(
        self,
        key_str: Optional[str] = None,
        *,
        keyring_json: Optional[str] = None,
        write_key_id: Optional[str] = None,
    ):
        self._legacy_key: Optional[bytes] = None
        self._keyring: dict[str, bytes] = {}
        self._write_key_id: Optional[str] = None
        self._configuration_error = _KEY_REQUIRED_MESSAGE
        if keyring_json:
            self._load_keyring(keyring_json, write_key_id)
            if self._configuration_error:
                return
            if key_str:
                self._legacy_key = self._decode_key(key_str, "JOYSAFETER_VAULT_ENCRYPTION_KEY")
            return
        if write_key_id:
            self._configuration_error = (
                "JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING is required when "
                "JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID is configured"
            )
            return
        if key_str:
            self._legacy_key = self._decode_key(key_str, "JOYSAFETER_VAULT_ENCRYPTION_KEY")
            if self._legacy_key is not None:
                self._configuration_error = ""

    def _decode_key(self, key_str: str, setting_name: str) -> Optional[bytes]:
        key_str = key_str.strip()
        try:
            if len(key_str) == _AES_KEY_SIZE * 2:
                key_bytes = bytes.fromhex(key_str)
            else:
                key_bytes = base64.b64decode(key_str, validate=True)
        except (ValueError, binascii.Error):
            self._configuration_error = f"{setting_name} must be a 32-byte hex or base64 value"
            return None

        if len(key_bytes) != _AES_KEY_SIZE:
            self._configuration_error = f"{setting_name} must decode to {_AES_KEY_SIZE} bytes"
            return None

        return key_bytes

    def _load_keyring(self, keyring_json: str, write_key_id: Optional[str]) -> None:
        try:
            raw_keyring = json.loads(keyring_json)
        except (TypeError, json.JSONDecodeError):
            self._configuration_error = "JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING must be a JSON object"
            return
        if not isinstance(raw_keyring, dict) or not raw_keyring:
            self._configuration_error = "JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING must be a non-empty JSON object"
            return

        parsed: dict[str, bytes] = {}
        for key_id, raw_key in raw_keyring.items():
            if not isinstance(key_id, str) or _KEY_ID_PATTERN.fullmatch(key_id) is None:
                self._configuration_error = (
                    "JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING key ids must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
                )
                return
            if not isinstance(raw_key, str):
                self._configuration_error = f"JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING[{key_id!r}] must be a string"
                return
            key = self._decode_key(
                raw_key,
                f"JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING[{key_id!r}]",
            )
            if key is None:
                return
            parsed[key_id] = key

        if not write_key_id:
            self._configuration_error = "JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID write key id is required"
            return
        if write_key_id not in parsed:
            self._configuration_error = (
                "JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID write key id is not present in the keyring"
            )
            return

        self._keyring = parsed
        self._write_key_id = write_key_id
        self._configuration_error = ""

    def require_enabled(self) -> None:
        if self._configuration_error:
            raise CredentialCipherConfigurationError(self._configuration_error)

    @property
    def configured_key_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._keyring))

    @property
    def has_legacy_key(self) -> bool:
        return self._legacy_key is not None

    @property
    def write_key_id(self) -> str | None:
        return self._write_key_id

    @property
    def active_envelope_prefix(self) -> str:
        if self._write_key_id is None:
            return _V1_ENCRYPTED_PREFIX
        return f"{_V2_ENCRYPTED_PREFIX}{self._write_key_id}:"

    def encrypt_for_key_id(self, plaintext: str, key_id: str) -> str:
        self.require_enabled()
        key = self._keyring.get(key_id)
        if key is None:
            raise CredentialCipherConfigurationError(f"Credential encryption key id is not configured: {key_id}")
        return self._encrypt_with_key(plaintext, key, f"{_V2_ENCRYPTED_PREFIX}{key_id}:")

    def encrypt(self, plaintext: str) -> str:
        self.require_enabled()
        if self._write_key_id is not None:
            key_id = self._write_key_id
            key = self._keyring[key_id]
            prefix = f"{_V2_ENCRYPTED_PREFIX}{key_id}:"
        else:
            assert self._legacy_key is not None
            key = self._legacy_key
            prefix = _V1_ENCRYPTED_PREFIX

        return self._encrypt_with_key(plaintext, key, prefix)

    @staticmethod
    def _encrypt_with_key(plaintext: str, key: bytes, prefix: str) -> str:
        nonce = secrets.token_bytes(_NONCE_SIZE)
        aad = prefix.encode("ascii") if prefix.startswith(_V2_ENCRYPTED_PREFIX) else None
        ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad)
        return prefix + base64.b64encode(nonce + ciphertext).decode("ascii")

    def _key_payload_and_aad(self, stored: str) -> tuple[bytes, str, bytes | None]:
        if stored.startswith(_V2_ENCRYPTED_PREFIX):
            remainder = stored[len(_V2_ENCRYPTED_PREFIX) :]
            key_id, separator, payload = remainder.partition(":")
            if not separator or not key_id or not payload:
                raise CredentialCiphertextError("Unsupported credential envelope")
            key = self._keyring.get(key_id)
            if key is None:
                raise CredentialCipherConfigurationError(f"Credential encryption key id is not configured: {key_id}")
            return key, payload, f"{_V2_ENCRYPTED_PREFIX}{key_id}:".encode("ascii")
        if stored.startswith(_V1_ENCRYPTED_PREFIX):
            if self._legacy_key is None:
                raise CredentialCipherConfigurationError(
                    "JOYSAFETER_VAULT_ENCRYPTION_KEY is required to decrypt enc:v1 material"
                )
            return self._legacy_key, stored[len(_V1_ENCRYPTED_PREFIX) :], None
        if stored.startswith("enc:v") and ":" in stored[len("enc:v") :]:
            raise CredentialCiphertextError("Unsupported credential envelope")
        if stored.startswith(_LEGACY_ENCRYPTED_PREFIX):
            if self._legacy_key is None:
                raise CredentialCipherConfigurationError(
                    "JOYSAFETER_VAULT_ENCRYPTION_KEY is required to decrypt legacy enc material"
                )
            return self._legacy_key, stored[len(_LEGACY_ENCRYPTED_PREFIX) :], None
        raise CredentialCiphertextError("Stored credential is not encrypted")

    def decrypt_stored(self, stored: str) -> str:
        if stored == "":
            return ""
        self.require_enabled()

        try:
            key, payload, aad = self._key_payload_and_aad(stored)
            raw = base64.b64decode(payload, validate=True)
            if len(raw) < _NONCE_SIZE + _TAG_SIZE:
                raise ValueError("ciphertext payload is too short")
            nonce = raw[:_NONCE_SIZE]
            ciphertext = raw[_NONCE_SIZE:]
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad)
            return plaintext.decode("utf-8")
        except Exception as exc:
            if isinstance(exc, (CredentialCipherConfigurationError, CredentialCiphertextError)):
                raise
            raise CredentialCiphertextError("Failed to decrypt stored credential") from exc

    def normalize_stored(self, stored: str) -> str:
        if stored == "":
            return ""
        if self._write_key_id is None and stored.startswith(_V1_ENCRYPTED_PREFIX):
            self.decrypt_stored(stored)
            return stored
        if self._write_key_id is not None and stored.startswith(f"{_V2_ENCRYPTED_PREFIX}{self._write_key_id}:"):
            self.decrypt_stored(stored)
            return stored
        if stored.startswith("enc:v") and ":" in stored[len("enc:v") :]:
            return self.encrypt(self.decrypt_stored(stored))
        if stored.startswith(_LEGACY_ENCRYPTED_PREFIX):
            self.decrypt_stored(stored)
            if self._write_key_id is None:
                return _V1_ENCRYPTED_PREFIX + stored[len(_LEGACY_ENCRYPTED_PREFIX) :]
            return self.encrypt(self.decrypt_stored(stored))
        return self.encrypt(stored)

    @staticmethod
    def generate_key() -> str:
        return base64.b64encode(secrets.token_bytes(_AES_KEY_SIZE)).decode("ascii")
