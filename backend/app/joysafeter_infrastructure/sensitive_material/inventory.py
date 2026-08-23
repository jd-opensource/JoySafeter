from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.security.credential_cipher import (
    CredentialCipher,
    CredentialCipherConfigurationError,
)


@dataclass(frozen=True, slots=True)
class SensitiveMaterialEnvelopeInventory:
    surface: str
    envelope: str
    count: int


async def inspect_sensitive_material_envelopes(
    db: AsyncSession,
) -> tuple[SensitiveMaterialEnvelopeInventory, ...]:
    rows = (
        await db.execute(
            text(
                "WITH material(surface, stored, invalid_shape) AS ("
                "SELECT 'managed_credential.data', item.value, false "
                "FROM joysafeter_credentials "
                "CROSS JOIN LATERAL jsonb_each_text("
                "CASE WHEN jsonb_typeof(joysafeter_credentials.data) = 'object' "
                "THEN joysafeter_credentials.data ELSE '{}'::jsonb END"
                ") AS item "
                "UNION ALL "
                "SELECT 'managed_credential.data', NULL::text, true "
                "FROM joysafeter_credentials "
                "WHERE jsonb_typeof(joysafeter_credentials.data) IS DISTINCT FROM 'object' "
                "UNION ALL "
                "SELECT 'managed_credential.oauth_config', item.value, false "
                "FROM joysafeter_credentials "
                "CROSS JOIN LATERAL jsonb_each_text("
                "CASE WHEN jsonb_typeof(joysafeter_credentials.oauth_config) = 'object' "
                "THEN joysafeter_credentials.oauth_config ELSE '{}'::jsonb END"
                ") AS item "
                "WHERE joysafeter_credentials.oauth_config IS NOT NULL "
                "AND item.key IN ('client_secret', 'refresh_token') "
                "UNION ALL "
                "SELECT 'managed_credential.oauth_config', NULL::text, true "
                "FROM joysafeter_credentials "
                "WHERE joysafeter_credentials.oauth_config IS NOT NULL "
                "AND jsonb_typeof(joysafeter_credentials.oauth_config) IS DISTINCT FROM 'object' "
                "UNION ALL "
                "SELECT 'task_identity', encrypted_credential, false "
                "FROM joysafeter_task_identity_contexts WHERE encrypted_credential IS NOT NULL "
                "UNION ALL "
                "SELECT 'repository_token', encrypted_token, false "
                "FROM joysafeter_session_repos WHERE encrypted_token <> ''"
                "), classified AS ("
                "SELECT surface, CASE "
                "WHEN invalid_shape OR stored IS NULL THEN 'invalid-or-plaintext' "
                "WHEN stored ~ '^enc:v2:[A-Za-z0-9][A-Za-z0-9._-]{0,127}:.+$' "
                "THEN 'enc:v2:' || substring(stored FROM '^enc:v2:([^:]+):') "
                "WHEN stored LIKE 'enc:v1:%' AND length(stored) > length('enc:v1:') THEN 'enc:v1' "
                "WHEN stored ~ '^enc:v[^:]*:' THEN 'invalid-or-plaintext' "
                "WHEN stored LIKE 'enc:%' AND length(stored) > length('enc:') THEN 'enc:legacy' "
                "ELSE 'invalid-or-plaintext' END AS envelope "
                "FROM material WHERE invalid_shape OR stored IS NULL OR stored <> ''"
                ") SELECT surface, envelope, count(*) AS count "
                "FROM classified GROUP BY surface, envelope ORDER BY surface, envelope"
            )
        )
    ).mappings()
    return tuple(
        SensitiveMaterialEnvelopeInventory(
            surface=str(row["surface"]),
            envelope=str(row["envelope"]),
            count=int(row["count"]),
        )
        for row in rows
    )


async def validate_credential_encryption_storage_coverage(
    db: AsyncSession,
    cipher: CredentialCipher,
) -> None:
    cipher.require_enabled()
    inventory = await inspect_sensitive_material_envelopes(db)
    invalid = [entry for entry in inventory if entry.envelope == "invalid-or-plaintext"]
    if invalid:
        locations = ", ".join(f"{entry.surface}={entry.count}" for entry in invalid)
        raise CredentialCipherConfigurationError(
            f"Credential storage contains invalid or plaintext envelopes: {locations}"
        )

    legacy = [entry for entry in inventory if entry.envelope in {"enc:legacy", "enc:v1"}]
    if legacy and not cipher.has_legacy_key:
        locations = ", ".join(f"{entry.surface}:{entry.envelope}={entry.count}" for entry in legacy)
        raise CredentialCipherConfigurationError(
            "Credential storage still requires JOYSAFETER_VAULT_ENCRYPTION_KEY: " + locations
        )

    configured_key_ids = set(cipher.configured_key_ids)
    referenced_key_ids = {
        entry.envelope.removeprefix("enc:v2:") for entry in inventory if entry.envelope.startswith("enc:v2:")
    }
    missing_key_ids = sorted(referenced_key_ids - configured_key_ids)
    if missing_key_ids:
        raise CredentialCipherConfigurationError(
            "Credential storage references unconfigured encryption key ids: " + ", ".join(missing_key_ids)
        )
