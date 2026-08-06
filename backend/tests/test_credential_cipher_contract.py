import pytest

from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_domain.services.joysafeter_vault_service import VaultService
from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.runtime.lifecycle import validate_credential_encryption_configuration
from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipher,
    CredentialCipherConfigurationError,
    CredentialCiphertextError,
)

pytestmark = pytest.mark.no_db


def test_credential_cipher_requires_configured_key_for_every_operation():
    cipher = CredentialCipher()

    with pytest.raises(CredentialCipherConfigurationError):
        cipher.encrypt("secret")
    with pytest.raises(CredentialCipherConfigurationError):
        cipher.decrypt_stored("enc:anything")


def test_service_startup_rejects_missing_credential_encryption_key(monkeypatch):
    monkeypatch.setattr(joysafeter_config, "vault_encryption_key", None)

    with pytest.raises(CredentialCipherConfigurationError):
        validate_credential_encryption_configuration()


@pytest.mark.parametrize("key", ["not-base64", "00", "CHANGE_ME"])
def test_credential_cipher_rejects_invalid_keys(key: str):
    with pytest.raises(CredentialCipherConfigurationError):
        CredentialCipher(key).require_enabled()


def test_credential_cipher_rejects_plaintext_and_tampered_storage():
    cipher = CredentialCipher(CredentialCipher.generate_key())

    with pytest.raises(CredentialCiphertextError, match="not encrypted"):
        cipher.decrypt_stored("plaintext-secret")
    with pytest.raises(CredentialCiphertextError, match="Failed to decrypt"):
        cipher.decrypt_stored("enc:not-valid-base64")


def test_credential_cipher_round_trip_uses_encrypted_storage_envelope():
    cipher = CredentialCipher(CredentialCipher.generate_key())

    stored = cipher.encrypt("secret-value")

    assert stored.startswith("enc:")
    assert stored != "secret-value"
    assert cipher.decrypt_stored(stored) == "secret-value"


def test_vault_oauth_input_cannot_bypass_encryption_with_enc_prefix(monkeypatch):
    cipher = CredentialCipher(CredentialCipher.generate_key())
    monkeypatch.setattr("app.joysafeter_domain.services.joysafeter_vault_service._cipher", cipher)
    service = VaultService(db=None)  # type: ignore[arg-type]

    stored = service._encrypt_oauth_config_for_storage({"client_secret": "enc:client-input"})

    assert stored is not None
    assert stored["client_secret"] != "enc:client-input"
    assert cipher.decrypt_stored(stored["client_secret"]) == "enc:client-input"


def test_vault_runtime_never_returns_plaintext_or_ciphertext_on_decrypt_failure(monkeypatch):
    cipher = CredentialCipher(CredentialCipher.generate_key())
    monkeypatch.setattr("app.joysafeter_domain.services.joysafeter_vault_service._cipher", cipher)
    service = VaultService(db=None)  # type: ignore[arg-type]

    with pytest.raises(CredentialCiphertextError):
        service._decrypt_token_value("plaintext-token")
    with pytest.raises(CredentialCiphertextError):
        service._decrypt_token_value("enc:broken")


def test_secret_runtime_rejects_plaintext_storage(monkeypatch):
    cipher = CredentialCipher(CredentialCipher.generate_key())
    monkeypatch.setattr("app.joysafeter_domain.services.joysafeter_secret_service._cipher", cipher)
    service = SecretService(db=None)  # type: ignore[arg-type]

    with pytest.raises(CredentialCiphertextError):
        service.decrypt_data({"TOKEN": "plaintext-token"})
