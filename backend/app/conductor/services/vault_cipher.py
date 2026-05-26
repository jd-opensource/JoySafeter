import base64
import logging
import os
import secrets
from typing import Optional

logger = logging.getLogger(__name__)

_AES_KEY_SIZE = 32  # 256 bits
_NONCE_SIZE = 12    # 96 bits for GCM
_TAG_SIZE = 16      # 128 bits


class VaultCipher:
    """AES-256-GCM encryption for vault credential storage.

    Key is loaded from conductor_config.vault_encryption_key (base64-encoded 32 bytes).
    If no key is configured, encrypt/decrypt are pass-through (development mode).
    """

    def __init__(self, key_str: Optional[str] = None):
        self._key: Optional[bytes] = None
        if key_str:
            try:
                # Try hex first (Rust-compatible), fall back to base64
                try:
                    key_bytes = bytes.fromhex(key_str)
                except ValueError:
                    key_bytes = base64.b64decode(key_str)
                self._key = key_bytes
                if len(self._key) != _AES_KEY_SIZE:
                    logger.error(
                        "Vault encryption key must be %d bytes, got %d",
                        _AES_KEY_SIZE, len(self._key),
                    )
                    self._key = None
            except Exception as e:
                logger.error("Invalid vault encryption key: %s", e)

    @property
    def is_enabled(self) -> bool:
        return self._key is not None

    def encrypt(self, plaintext: str) -> str:
        if not self._key:
            return plaintext

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = secrets.token_bytes(_NONCE_SIZE)
        aes = AESGCM(self._key)
        ciphertext = aes.encrypt(nonce, plaintext.encode("utf-8"), None)

        # Format: enc:<base64(nonce + ciphertext_with_tag)>
        # Matches Rust agentd AES-256-GCM wire format
        return "enc:" + base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, encrypted: str) -> str:
        if not self._key:
            return encrypted

        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        try:
            raw = base64.b64decode(encrypted)
            nonce = raw[:_NONCE_SIZE]
            ciphertext = raw[_NONCE_SIZE:]
            aes = AESGCM(self._key)
            plaintext = aes.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as e:
            logger.error("Vault decryption failed: %s", e)
            raise ValueError("Failed to decrypt vault credential") from e

    @staticmethod
    def generate_key() -> str:
        return base64.b64encode(secrets.token_bytes(_AES_KEY_SIZE)).decode("ascii")

    def decrypt_or_passthrough(self, stored: str) -> str:
        """Decrypt if stored starts with 'enc:' prefix, otherwise return as-is (plaintext passthrough)."""
        if stored.startswith("enc:"):
            return self.decrypt(stored[4:])
        return stored
