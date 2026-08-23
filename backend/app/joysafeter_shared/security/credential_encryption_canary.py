from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipher,
    CredentialCipherConfigurationError,
    CredentialCiphertextError,
)

_CANARY_PREFIX = "joysafeter-credential-encryption-canary:"


def _canary_plaintext(key_id: str) -> str:
    return f"{_CANARY_PREFIX}{key_id}"


async def validate_credential_encryption_canaries(
    db: AsyncSession,
    cipher: CredentialCipher,
) -> None:
    key_ids = cipher.configured_key_ids
    if not key_ids:
        return

    statement = text(
        "SELECT key_id, encrypted_canary FROM joysafeter_credential_encryption_canaries WHERE key_id IN :key_ids"
    ).bindparams(bindparam("key_ids", expanding=True))
    rows = (await db.execute(statement, {"key_ids": key_ids})).mappings().all()
    by_key_id = {str(row["key_id"]): str(row["encrypted_canary"]) for row in rows}
    missing = sorted(set(key_ids) - set(by_key_id))
    if missing:
        raise CredentialCipherConfigurationError(
            "Credential encryption canary is missing for key ids: " + ", ".join(missing)
        )

    for key_id in key_ids:
        try:
            plaintext = cipher.decrypt_stored(by_key_id[key_id])
        except (CredentialCipherConfigurationError, CredentialCiphertextError) as exc:
            raise CredentialCipherConfigurationError(
                f"Credential encryption canary cannot be decrypted for key id: {key_id}"
            ) from exc
        if plaintext != _canary_plaintext(key_id):
            raise CredentialCipherConfigurationError(
                f"Credential encryption canary plaintext is invalid for key id: {key_id}"
            )


async def initialize_missing_credential_encryption_canaries(
    db: AsyncSession,
    cipher: CredentialCipher,
) -> tuple[str, ...]:
    key_ids = cipher.configured_key_ids
    if not key_ids:
        raise CredentialCipherConfigurationError("A credential encryption keyring is required to initialize canaries")

    created: list[str] = []
    async with db.begin_nested():
        existing_statement = text(
            "SELECT key_id, encrypted_canary "
            "FROM joysafeter_credential_encryption_canaries "
            "WHERE key_id IN :key_ids FOR UPDATE"
        ).bindparams(bindparam("key_ids", expanding=True))
        rows = (await db.execute(existing_statement, {"key_ids": key_ids})).mappings().all()
        existing = {str(row["key_id"]): str(row["encrypted_canary"]) for row in rows}

        for key_id, encrypted_canary in existing.items():
            try:
                plaintext = cipher.decrypt_stored(encrypted_canary)
            except (CredentialCipherConfigurationError, CredentialCiphertextError) as exc:
                raise CredentialCipherConfigurationError(
                    f"Credential encryption canary cannot be decrypted for key id: {key_id}"
                ) from exc
            if plaintext != _canary_plaintext(key_id):
                raise CredentialCipherConfigurationError(
                    f"Credential encryption canary plaintext is invalid for key id: {key_id}"
                )

        for key_id in key_ids:
            if key_id in existing:
                continue
            inserted_key_id = await db.scalar(
                text(
                    "INSERT INTO joysafeter_credential_encryption_canaries (key_id, encrypted_canary) "
                    "VALUES (:key_id, :encrypted_canary) "
                    "ON CONFLICT (key_id) DO NOTHING "
                    "RETURNING key_id"
                ),
                {
                    "key_id": key_id,
                    "encrypted_canary": cipher.encrypt_for_key_id(_canary_plaintext(key_id), key_id),
                },
            )
            if inserted_key_id is not None:
                created.append(str(inserted_key_id))

        await validate_credential_encryption_canaries(db, cipher)
    return tuple(created)
