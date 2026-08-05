"""Credential masking must be default-deny.

Secret values and vault credential tokens are returned to any project reader via
GET/list. The masking must default to hiding EVERYTHING and only reveal a small
allowlist of display-safe config keys (base_url / model / provider ...). The
previous behaviour leaked any value whose key name did not happen to contain
KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL (e.g. CONNECTION_STRING, DSN) in cleartext,
and vault tokens leaked their first 6 characters (or the whole short token).
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.joysafeter_domain.schemas.joysafeter_vault import VaultCredentialResponse
from app.joysafeter_domain.services.joysafeter_secret_service import MASKED_SECRET_PREFIX, SecretService

pytestmark = pytest.mark.no_db


def _svc() -> SecretService:
    # get_masked_secret_data only decrypts + masks; it never touches the DB.
    return SecretService(db=None)  # type: ignore[arg-type]


def test_secret_masking_hides_non_conventionally_named_secret():
    secret = SimpleNamespace(
        data={
            "OPENAI_API_KEY": "sk-super-secret-value",
            "CONNECTION_STRING": "postgres://user:pa55w0rd@host/db",
            "DSN": "user=admin password=hunter2",
        }
    )
    masked = _svc().get_masked_secret_data(secret)  # type: ignore[arg-type]

    assert masked["OPENAI_API_KEY"].startswith(MASKED_SECRET_PREFIX)
    # The headline leak: an unconventionally-named secret must NOT be cleartext.
    assert "pa55w0rd" not in masked["CONNECTION_STRING"]
    assert masked["CONNECTION_STRING"].startswith(MASKED_SECRET_PREFIX)
    assert "hunter2" not in masked["DSN"]
    assert masked["DSN"].startswith(MASKED_SECRET_PREFIX)


def test_secret_masking_reveals_display_safe_config_keys():
    secret = SimpleNamespace(
        data={
            "OPENAI_BASE_URL": "https://api.example.com/v1",
            "OPENAI_MODEL": "gpt-5.3",
            "PROVIDER": "openai",
        }
    )
    masked = _svc().get_masked_secret_data(secret)  # type: ignore[arg-type]

    assert masked["OPENAI_BASE_URL"] == "https://api.example.com/v1"
    assert masked["OPENAI_MODEL"] == "gpt-5.3"
    assert masked["PROVIDER"] == "openai"


def _vault_response(token_value: str) -> dict:
    model = VaultCredentialResponse(
        id=uuid.uuid4(),
        vault_id=uuid.uuid4(),
        name="cred",
        credential_type="token",
        mcp_server_url="https://mcp.example.com",
        token_value=token_value,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return model.model_dump()


def test_vault_plaintext_token_is_fully_redacted_not_prefix_leaked():
    dumped = _vault_response("plaintexttoken1234567890")
    assert "plaint" not in dumped["token_value"], "must not leak the first characters of a token"
    assert dumped["token_value"] == "********"


def test_vault_short_token_is_not_leaked_whole():
    dumped = _vault_response("abc")
    assert dumped["token_value"] == "********"
    assert "abc" not in dumped["token_value"]


def test_vault_oauth_secrets_fully_redacted():
    model = VaultCredentialResponse(
        id=uuid.uuid4(),
        vault_id=uuid.uuid4(),
        name="cred",
        credential_type="oauth",
        mcp_server_url="https://mcp.example.com",
        token_value="",
        oauth_config={"client_id": "public-id", "client_secret": "shhh-secret-value", "refresh_token": "rt-value-xyz"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    dumped = model.model_dump()
    assert dumped["oauth_config"]["client_secret"] == "********"
    assert dumped["oauth_config"]["refresh_token"] == "********"
    assert "shhh" not in dumped["oauth_config"]["client_secret"]
    # A non-secret field like client_id may remain visible.
    assert dumped["oauth_config"]["client_id"] == "public-id"
