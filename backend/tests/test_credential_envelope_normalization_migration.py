from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.joysafeter_shared.security.credential_cipher import CredentialCipher

pytestmark = pytest.mark.no_db

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260815_000001_normalize_credential_envelopes.py"
)
VAULT_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _migration_module():
    spec = importlib.util.spec_from_file_location("credential_envelope_normalization", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _legacy(cipher: CredentialCipher, plaintext: str) -> str:
    current = cipher.encrypt(plaintext)
    return "enc:" + current[len("enc:v1:") :]


def test_alembic_heads_does_not_require_runtime_secrets():
    env = os.environ.copy()
    env.pop("SECRET_KEY", None)
    env.pop("JOYSAFETER_VAULT_ENCRYPTION_KEY", None)

    result = subprocess.run(
        [Path(sys.executable).with_name("alembic"), "heads"],
        cwd=MIGRATION_PATH.parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "20260823_000005 (head)" in result.stdout


def test_normalize_value_handles_empty_plaintext_legacy_and_current():
    migration = _migration_module()
    cipher = CredentialCipher(VAULT_KEY)
    current = cipher.encrypt("current")
    legacy = _legacy(cipher, "legacy")

    assert migration._normalize_value(cipher, "", "row.empty") == ""
    assert migration._normalize_value(cipher, current, "row.current") == current

    normalized_legacy = migration._normalize_value(cipher, legacy, "row.legacy")
    assert normalized_legacy.startswith("enc:v1:")
    assert cipher.decrypt_stored(normalized_legacy) == "legacy"

    normalized_plaintext = migration._normalize_value(cipher, "plaintext", "row.plaintext")
    assert normalized_plaintext.startswith("enc:v1:")
    assert cipher.decrypt_stored(normalized_plaintext) == "plaintext"


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (123, "must be a JSON string"),
        ("enc:v2:not-supported", "Unsupported credential envelope"),
        ("enc:not-valid-base64", "Failed to decrypt"),
    ],
)
def test_normalize_value_reports_location_for_invalid_storage(value: object, message: str):
    migration = _migration_module()

    with pytest.raises(RuntimeError, match=f"credential.data.API_KEY.*{message}"):
        migration._normalize_value(CredentialCipher(VAULT_KEY), value, "credential.data.API_KEY")


def test_normalize_object_can_limit_normalization_to_oauth_secret_fields():
    migration = _migration_module()
    cipher = CredentialCipher(VAULT_KEY)
    value = {
        "client_id": "public-client",
        "client_secret": "plaintext-secret",
        "refresh_token": _legacy(cipher, "refresh"),
        "expires_at": 123,
    }

    normalized = migration._normalize_object(
        cipher,
        value,
        "credential.oauth_config",
        keys=frozenset({"client_secret", "refresh_token"}),
    )

    assert normalized["client_id"] == "public-client"
    assert normalized["expires_at"] == 123
    assert cipher.decrypt_stored(normalized["client_secret"]) == "plaintext-secret"
    assert cipher.decrypt_stored(normalized["refresh_token"]) == "refresh"
