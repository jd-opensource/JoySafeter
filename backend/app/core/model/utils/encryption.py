"""
Credential encryption/decryption utilities.
"""

import base64
import json
from typing import Any, Dict

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.core.settings import settings


class CredentialEncryption:
    """Credential encryption handler."""

    def __init__(self, key: str | None = None):
        """
        Initialize the encryptor.

        Args:
            key: encryption key; if None, read from settings or generate one
        """
        if key is None:
            # read key from settings; fall back to generating one (production should use env var)
            key = getattr(settings, "credential_encryption_key", None)
            if key is None:
                # generate a default key (development only)
                key = Fernet.generate_key().decode()

        if isinstance(key, str):
            key_bytes = key.encode()
        else:
            key_bytes = key

        # if the key is not in Fernet format, derive via PBKDF2
        try:
            self.fernet = Fernet(key_bytes)
        except ValueError:
            # key is not Fernet-formatted; derive via PBKDF2
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"credential_salt",  # production should use a random salt
                iterations=100000,
            )
            key_bytes = base64.urlsafe_b64encode(kdf.derive(key_bytes))
            self.fernet = Fernet(key_bytes)

    def encrypt(self, data: Dict[str, Any]) -> str:
        """
        Encrypt credential data.

        Args:
            data: credential dict to encrypt

        Returns:
            Encrypted string (base64-encoded).
        """
        json_str = json.dumps(data, ensure_ascii=False)
        encrypted = self.fernet.encrypt(json_str.encode())
        return base64.urlsafe_b64encode(encrypted).decode()

    def decrypt(self, encrypted_data: str) -> Dict[str, Any]:
        """
        Decrypt credential data.

        Args:
            encrypted_data: encrypted string (base64-encoded)

        Returns:
            Decrypted credential dict.
        """
        encrypted_bytes = base64.urlsafe_b64decode(encrypted_data.encode())
        decrypted_bytes = self.fernet.decrypt(encrypted_bytes)
        result = json.loads(decrypted_bytes.decode())
        return result if isinstance(result, dict) else {}


# global encryptor instance
_default_encryption = None


def get_encryption() -> CredentialEncryption:
    """Return the global encryptor instance."""
    global _default_encryption
    if _default_encryption is None:
        _default_encryption = CredentialEncryption()
    return _default_encryption


def encrypt_credentials(credentials: Dict[str, Any], key: str | None = None) -> str:
    """
    Encrypt credentials.

    Args:
        credentials: credential dict
        key: encryption key; if None, use the default key

    Returns:
        Encrypted string.
    """
    encryption = CredentialEncryption(key) if key else get_encryption()
    return encryption.encrypt(credentials)


def decrypt_credentials(encrypted_data: str, key: str | None = None) -> Dict[str, Any]:
    """
    Decrypt credentials.

    Args:
        encrypted_data: encrypted string
        key: encryption key; if None, use the default key

    Returns:
        Decrypted credential dict.
    """
    encryption = CredentialEncryption(key) if key else get_encryption()
    return encryption.decrypt(encrypted_data)
