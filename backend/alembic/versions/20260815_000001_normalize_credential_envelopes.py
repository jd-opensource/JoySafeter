"""Normalize every persisted credential value to the enc:v1 envelope.

Revision ID: 20260815_000001
Revises: 20260814_000002
Create Date: 2026-08-15 00:00:00.000000

This migration is online-only and irreversible. It performs a complete
cryptographic preflight before issuing updates; any validation or write failure
rolls the surrounding PostgreSQL transaction back to ``20260814_000002``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Optional, Union

import sqlalchemy as sa

from alembic import context, op

if TYPE_CHECKING:
    from app.joysafeter_shared.security.credential_cipher import CredentialCipher

revision: str = "20260815_000001"
down_revision: Union[str, None] = "20260814_000002"
branch_labels: Optional[str] = None
depends_on: Optional[str] = None

_OAUTH_SECRET_FIELDS = frozenset({"client_secret", "refresh_token"})


def _normalize_value(cipher: CredentialCipher, value: object, location: str) -> str:
    from app.joysafeter_shared.security.credential_cipher import CredentialCiphertextError

    if not isinstance(value, str):
        raise RuntimeError(f"Credential value at {location} must be a JSON string")
    try:
        normalized = cipher.normalize_stored(value)
        if normalized:
            if not normalized.startswith("enc:v1:"):
                raise CredentialCiphertextError("Normalized credential is not enc:v1")
            cipher.decrypt_stored(normalized)
        return normalized
    except CredentialCiphertextError as exc:
        raise RuntimeError(f"Credential envelope normalization failed at {location}: {exc}") from exc


def _normalize_object(
    cipher: CredentialCipher,
    value: object,
    location: str,
    *,
    keys: frozenset[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError(f"Credential object at {location} must be a JSON object")
    normalized = dict(value)
    selected_keys = value.keys() if keys is None else (key for key in keys if key in value)
    for key in selected_keys:
        normalized[key] = _normalize_value(cipher, value[key], f"{location}.{key}")
    return normalized


def _prepare_credential_updates(
    connection: sa.engine.Connection,
    cipher: CredentialCipher,
) -> list[dict[str, object]]:
    rows = connection.execute(
        sa.text("SELECT id, name, data, oauth_config FROM joysafeter_credentials ORDER BY id FOR UPDATE")
    ).mappings()
    updates: list[dict[str, object]] = []
    for row in rows:
        name = str(row["name"])
        data = row["data"]
        oauth_config = row["oauth_config"]
        normalized_data = _normalize_object(cipher, data, f"{name}.data")
        normalized_oauth = (
            None
            if oauth_config is None
            else _normalize_object(
                cipher,
                oauth_config,
                f"{name}.oauth_config",
                keys=_OAUTH_SECRET_FIELDS,
            )
        )
        if normalized_data != data or normalized_oauth != oauth_config:
            updates.append(
                {
                    "id": row["id"],
                    "data": normalized_data,
                    "oauth_config": normalized_oauth,
                    "data_changed": normalized_data != data,
                    "oauth_changed": normalized_oauth != oauth_config,
                }
            )
    return updates


def _prepare_text_updates(
    connection: sa.engine.Connection,
    cipher: CredentialCipher,
    *,
    table: str,
    id_column: str,
    value_column: str,
    nullable: bool = False,
) -> list[dict[str, object]]:
    where = f" WHERE {value_column} IS NOT NULL" if nullable else ""
    rows = connection.execute(
        sa.text(
            f"SELECT {id_column} AS row_id, {value_column} AS stored "
            f"FROM {table}{where} ORDER BY {id_column} FOR UPDATE"
        )
    ).mappings()
    updates: list[dict[str, object]] = []
    for row in rows:
        stored = row["stored"]
        normalized = _normalize_value(
            cipher,
            stored,
            f"{table}.{row['row_id']}.{value_column}",
        )
        if normalized != stored:
            updates.append({"row_id": row["row_id"], "stored": normalized})
    return updates


def _apply_credential_updates(
    connection: sa.engine.Connection,
    updates: list[dict[str, object]],
) -> None:
    for update in updates:
        if update["data_changed"]:
            connection.execute(
                sa.text("UPDATE joysafeter_credentials SET data = CAST(:data AS JSONB) WHERE id = :id"),
                {"id": update["id"], "data": json.dumps(update["data"])},
            )
        if update["oauth_changed"]:
            connection.execute(
                sa.text("UPDATE joysafeter_credentials SET oauth_config = CAST(:oauth_config AS JSONB) WHERE id = :id"),
                {
                    "id": update["id"],
                    "oauth_config": json.dumps(update["oauth_config"]),
                },
            )


def _apply_text_updates(
    connection: sa.engine.Connection,
    updates: list[dict[str, object]],
    *,
    table: str,
    id_column: str,
    value_column: str,
) -> None:
    statement = sa.text(f"UPDATE {table} SET {value_column} = :stored WHERE {id_column} = :row_id")
    for update in updates:
        connection.execute(statement, update)


def upgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError(
            "Migration 20260815_000001 is online-only because it validates and rewrites live credentials."
        )

    from app.joysafeter_shared.config.settings import joysafeter_config
    from app.joysafeter_shared.security.credential_cipher import CredentialCipher

    cipher = CredentialCipher(joysafeter_config.vault_encryption_key)
    cipher.require_enabled()
    connection = op.get_bind()

    credential_updates = _prepare_credential_updates(connection, cipher)
    repo_updates = _prepare_text_updates(
        connection,
        cipher,
        table="joysafeter_session_repos",
        id_column="id",
        value_column="encrypted_token",
    )
    identity_updates = _prepare_text_updates(
        connection,
        cipher,
        table="joysafeter_task_identity_contexts",
        id_column="task_id",
        value_column="encrypted_credential",
        nullable=True,
    )

    _apply_credential_updates(connection, credential_updates)
    _apply_text_updates(
        connection,
        repo_updates,
        table="joysafeter_session_repos",
        id_column="id",
        value_column="encrypted_token",
    )
    _apply_text_updates(
        connection,
        identity_updates,
        table="joysafeter_task_identity_contexts",
        id_column="task_id",
        value_column="encrypted_credential",
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade of 20260815_000001_normalize_credential_envelopes is not supported; "
        "restore the database backup taken before normalization."
    )
