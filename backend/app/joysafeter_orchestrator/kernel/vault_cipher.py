"""AES-256-GCM vault cipher for encrypting/decrypting secret values.

Ported from the Rust ``VaultCipher`` in
``joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs``.

Values persisted with the ``enc:`` prefix are base64-encoded payloads where the
first 12 bytes are the AES-GCM nonce and the remainder is the ciphertext
(including the 16-byte authentication tag appended by GCM).

The 256-bit key is read from the ``JOYSAFETER_VAULT_ENCRYPTION_KEY`` environment
variable, which may be hex-encoded (64 chars) or base64-encoded.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc:"
_NONCE_LENGTH = 12
_KEY_LENGTH = 32


class VaultCipher:
    """AES-256-GCM cipher for vault credential encryption.

    When no key is configured the caller should use ``from_env()`` which
    returns ``None``, and the caller can then skip encryption/decryption
    (passthrough semantics are the caller's responsibility when no cipher
    is available).
    """

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_LENGTH:
            raise ValueError(f"Vault encryption key must be {_KEY_LENGTH} bytes, got {len(key)}")
        self._key = key
        self._aesgcm = AESGCM(key)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> VaultCipher | None:
        """Create a ``VaultCipher`` from ``JOYSAFETER_VAULT_ENCRYPTION_KEY``.

        The environment variable is first decoded as hex; if that fails it is
        decoded as base64.  Returns ``None`` when the variable is unset or the
        decoded key is not exactly 32 bytes.
        """
        raw = os.environ.get("JOYSAFETER_VAULT_ENCRYPTION_KEY")
        if not raw:
            return None
        key = _parse_vault_key(raw)
        if key is None:
            logger.warning(
                "JOYSAFETER_VAULT_ENCRYPTION_KEY is set but could not be parsed as a 32-byte hex or base64 key"
            )
            return None
        return cls(key)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def decrypt_or_passthrough(self, value: str) -> str:
        """Decrypt an ``enc:``-prefixed value, or return *value* as-is.

        The payload after the prefix is base64-decoded.  The first 12 bytes are
        the nonce; the rest is the AES-256-GCM ciphertext (with appended tag).
        """
        if not value.startswith(_ENC_PREFIX):
            return value

        encoded = value[len(_ENC_PREFIX) :]
        raw = base64.b64decode(encoded)
        if len(raw) < _NONCE_LENGTH:
            raise ValueError("Encrypted vault value is too short")

        nonce = raw[:_NONCE_LENGTH]
        ciphertext = raw[_NONCE_LENGTH:]
        plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")

    def encrypt_or_passthrough(self, value: str) -> str:
        """Encrypt *value* with AES-256-GCM and add the ``enc:`` prefix.

        A random 12-byte nonce is generated, prepended to the ciphertext, and
        the combined bytes are base64-encoded.
        """
        nonce = os.urandom(_NONCE_LENGTH)
        ciphertext = self._aesgcm.encrypt(nonce, value.encode("utf-8"), None)
        raw = nonce + ciphertext
        return f"{_ENC_PREFIX}{base64.b64encode(raw).decode('ascii')}"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_vault_key(raw: str) -> bytes | None:
    """Decode a vault encryption key from hex or base64.

    Returns the raw 32-byte key, or ``None`` if decoding fails or the result
    is not exactly 32 bytes.
    """
    # Try hex first (matches Rust: hex::decode then base64 fallback)
    try:
        key = binascii.unhexlify(raw)
        if len(key) == _KEY_LENGTH:
            return key
    except (ValueError, binascii.Error):
        pass

    # Fall back to base64
    try:
        key = base64.b64decode(raw)
        if len(key) == _KEY_LENGTH:
            return key
    except Exception:
        pass

    return None
