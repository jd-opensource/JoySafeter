import json
from pathlib import Path

import pytest

from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.runtime.lifecycle import validate_credential_encryption_configuration
from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipher,
    CredentialCipherConfigurationError,
    CredentialCiphertextError,
)

pytestmark = pytest.mark.no_db

_CREDENTIAL_DOMAIN_CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts" / "credential_domain_contract.json").read_text()
)


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
        cipher.decrypt_stored("enc:v1:not-valid-base64")


def test_credential_cipher_rejects_unknown_versioned_envelope():
    cipher = CredentialCipher(CredentialCipher.generate_key())

    with pytest.raises(CredentialCiphertextError, match="Unsupported credential envelope"):
        cipher.decrypt_stored("enc:v2:not-supported")


def test_credential_cipher_round_trip_uses_encrypted_storage_envelope():
    cipher = CredentialCipher(CredentialCipher.generate_key())

    stored = cipher.encrypt("secret-value")

    assert stored.startswith(_CREDENTIAL_DOMAIN_CONTRACT["encryption_envelope"] + ":")
    assert stored != "secret-value"
    assert cipher.decrypt_stored(stored) == "secret-value"
