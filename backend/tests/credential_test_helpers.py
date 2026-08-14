from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.security.credential_cipher import CredentialCipher


def _cipher() -> CredentialCipher:
    cipher = CredentialCipher(joysafeter_config.vault_encryption_key)
    cipher.require_enabled()
    return cipher


def encrypted_secret_data(data: dict[str, str]) -> dict[str, str]:
    cipher = _cipher()
    return {str(key): cipher.encrypt(str(value)) for key, value in data.items()}


def encrypted_credential_value(value: str) -> str:
    return _cipher().encrypt(value)


def decrypted_credential_value(value: str) -> str:
    return _cipher().decrypt_stored(value)
