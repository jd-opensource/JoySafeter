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
    monkeypatch.setattr(joysafeter_config, "credential_encryption_keyring", None)
    monkeypatch.setattr(joysafeter_config, "credential_encryption_write_key_id", None)

    with pytest.raises(CredentialCipherConfigurationError):
        validate_credential_encryption_configuration()


def test_service_startup_accepts_keyring_without_legacy_key(monkeypatch):
    monkeypatch.setattr(joysafeter_config, "vault_encryption_key", None)
    monkeypatch.setattr(
        joysafeter_config,
        "credential_encryption_keyring",
        json.dumps({"active-2026-08": CredentialCipher.generate_key()}),
    )
    monkeypatch.setattr(
        joysafeter_config,
        "credential_encryption_write_key_id",
        "active-2026-08",
    )

    validate_credential_encryption_configuration()


@pytest.mark.parametrize("key", ["not-base64", "00", "CHANGE_ME"])
def test_credential_cipher_rejects_invalid_keys(key: str):
    with pytest.raises(CredentialCipherConfigurationError):
        CredentialCipher(key).require_enabled()


@pytest.mark.parametrize(
    "keyring",
    [
        "not-json",
        "[]",
        "{}",
        json.dumps({"active": "not-a-key"}),
        json.dumps({"bad:key-id": CredentialCipher.generate_key()}),
    ],
)
def test_credential_cipher_rejects_malformed_keyrings(keyring: str):
    with pytest.raises(CredentialCipherConfigurationError):
        CredentialCipher(
            keyring_json=keyring,
            write_key_id="active",
        ).require_enabled()


def test_credential_cipher_rejects_missing_or_unknown_write_key():
    keyring = json.dumps({"active": CredentialCipher.generate_key()})

    with pytest.raises(CredentialCipherConfigurationError, match="write key id is required"):
        CredentialCipher(keyring_json=keyring).require_enabled()
    with pytest.raises(CredentialCipherConfigurationError, match="write key id is not present"):
        CredentialCipher(keyring_json=keyring, write_key_id="unknown").require_enabled()


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

    assert stored.startswith(_CREDENTIAL_DOMAIN_CONTRACT["encryption_envelopes"]["legacy_read"][1])
    assert stored != "secret-value"
    assert cipher.decrypt_stored(stored) == "secret-value"


def test_credential_cipher_keyring_round_trip_uses_current_contract_envelope():
    key_id = "active-contract-key"
    cipher = CredentialCipher(
        keyring_json=json.dumps({key_id: CredentialCipher.generate_key()}),
        write_key_id=key_id,
    )

    stored = cipher.encrypt("secret-value")

    expected = _CREDENTIAL_DOMAIN_CONTRACT["encryption_envelopes"]["current_write"].replace("<key_id>", key_id)
    assert stored.startswith(expected)
    assert cipher.decrypt_stored(stored) == "secret-value"
