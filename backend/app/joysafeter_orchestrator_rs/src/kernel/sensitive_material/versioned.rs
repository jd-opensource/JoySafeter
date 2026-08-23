use std::collections::BTreeMap;

use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::Engine as _;
use sqlx::PgPool;
use thiserror::Error;

const LEGACY_KEY_ENV: &str = "JOYSAFETER_VAULT_ENCRYPTION_KEY";
const KEYRING_ENV: &str = "JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING";
const WRITE_KEY_ID_ENV: &str = "JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID";

#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum VersionedMaterialError {
    #[error("material encryption key configuration is missing or invalid")]
    KeyInvalid,
    #[error("material envelope is unsupported or malformed")]
    EnvelopeInvalid,
}

#[derive(Clone)]
pub struct VersionedMaterialProtector {
    legacy_key: Option<[u8; 32]>,
    keyring: BTreeMap<String, [u8; 32]>,
    configuration_valid: bool,
}

impl VersionedMaterialProtector {
    pub fn from_env() -> Self {
        Self::load_env().unwrap_or_else(|_| Self {
            legacy_key: None,
            keyring: BTreeMap::new(),
            configuration_valid: false,
        })
    }

    pub async fn validate_database_state(pool: &PgPool) -> anyhow::Result<()> {
        let protector = Self::load_env()?;
        let key_ids = protector.keyring.keys().cloned().collect::<Vec<_>>();

        if !key_ids.is_empty() {
            let rows = sqlx::query_as::<_, (String, String)>(
                "SELECT key_id, encrypted_canary \
                 FROM joysafeter_credential_encryption_canaries \
                 WHERE key_id = ANY($1)",
            )
            .bind(&key_ids)
            .fetch_all(pool)
            .await?;
            let canaries = rows.into_iter().collect::<BTreeMap<_, _>>();

            for key_id in key_ids {
                let encrypted_canary = canaries.get(&key_id).ok_or_else(|| {
                    anyhow::anyhow!("credential encryption canary is missing for key id: {key_id}")
                })?;
                let plaintext = protector.reveal(encrypted_canary).map_err(|_| {
                    anyhow::anyhow!(
                        "credential encryption canary cannot be decrypted for key id: {key_id}"
                    )
                })?;
                if plaintext != canary_plaintext(&key_id) {
                    anyhow::bail!(
                        "credential encryption canary plaintext is invalid for key id: {key_id}"
                    );
                }
            }
        }

        let inventory = sqlx::query_as::<_, (String, String, i64)>(
            "WITH material(surface, stored, invalid_shape) AS (\
             SELECT 'managed_credential.data', item.value, false \
             FROM joysafeter_credentials \
             CROSS JOIN LATERAL jsonb_each_text(\
             CASE WHEN jsonb_typeof(joysafeter_credentials.data) = 'object' \
             THEN joysafeter_credentials.data ELSE '{}'::jsonb END\
             ) AS item \
             UNION ALL \
             SELECT 'managed_credential.data', NULL::text, true \
             FROM joysafeter_credentials \
             WHERE jsonb_typeof(joysafeter_credentials.data) IS DISTINCT FROM 'object' \
             UNION ALL \
             SELECT 'managed_credential.oauth_config', item.value, false \
             FROM joysafeter_credentials \
             CROSS JOIN LATERAL jsonb_each_text(\
             CASE WHEN jsonb_typeof(joysafeter_credentials.oauth_config) = 'object' \
             THEN joysafeter_credentials.oauth_config ELSE '{}'::jsonb END\
             ) AS item \
             WHERE joysafeter_credentials.oauth_config IS NOT NULL \
             AND item.key IN ('client_secret', 'refresh_token') \
             UNION ALL \
             SELECT 'managed_credential.oauth_config', NULL::text, true \
             FROM joysafeter_credentials \
             WHERE joysafeter_credentials.oauth_config IS NOT NULL \
             AND jsonb_typeof(joysafeter_credentials.oauth_config) IS DISTINCT FROM 'object' \
             UNION ALL \
             SELECT 'task_identity', encrypted_credential, false \
             FROM joysafeter_task_identity_contexts WHERE encrypted_credential IS NOT NULL \
             UNION ALL \
             SELECT 'repository_token', encrypted_token, false \
             FROM joysafeter_session_repos WHERE encrypted_token <> ''\
             ), classified AS (\
             SELECT surface, CASE \
             WHEN invalid_shape OR stored IS NULL THEN 'invalid-or-plaintext' \
             WHEN stored ~ '^enc:v2:[A-Za-z0-9][A-Za-z0-9._-]{0,127}:.+$' \
             THEN 'enc:v2:' || substring(stored FROM '^enc:v2:([^:]+):') \
             WHEN stored LIKE 'enc:v1:%' AND length(stored) > length('enc:v1:') THEN 'enc:v1' \
             WHEN stored ~ '^enc:v[^:]*:' THEN 'invalid-or-plaintext' \
             WHEN stored LIKE 'enc:%' AND length(stored) > length('enc:') THEN 'enc:legacy' \
             ELSE 'invalid-or-plaintext' END AS envelope \
             FROM material WHERE invalid_shape OR stored IS NULL OR stored <> ''\
             ) SELECT surface, envelope, count(*)::bigint AS count \
             FROM classified GROUP BY surface, envelope ORDER BY surface, envelope",
        )
        .fetch_all(pool)
        .await?;
        for (surface, envelope, count) in inventory {
            protector
                .validate_envelope_reference(&envelope)
                .map_err(|_| {
                    anyhow::anyhow!(
                        "credential encryption storage coverage failed for {surface}: {envelope} ({count} row(s))"
                    )
                })?;
        }
        Ok(())
    }

    fn validate_envelope_reference(&self, envelope: &str) -> Result<(), VersionedMaterialError> {
        match envelope {
            "enc:legacy" | "enc:v1" => self
                .legacy_key
                .as_ref()
                .map(|_| ())
                .ok_or(VersionedMaterialError::KeyInvalid),
            "invalid-or-plaintext" => Err(VersionedMaterialError::EnvelopeInvalid),
            _ => envelope
                .strip_prefix("enc:v2:")
                .filter(|key_id| self.keyring.contains_key(*key_id))
                .map(|_| ())
                .ok_or(VersionedMaterialError::KeyInvalid),
        }
    }

    fn load_env() -> Result<Self, VersionedMaterialError> {
        let legacy_raw = std::env::var(LEGACY_KEY_ENV)
            .ok()
            .filter(|value| !value.trim().is_empty());
        let keyring_raw = std::env::var(KEYRING_ENV)
            .ok()
            .filter(|value| !value.trim().is_empty());
        let write_key_id = std::env::var(WRITE_KEY_ID_ENV)
            .ok()
            .filter(|value| !value.trim().is_empty());

        let legacy_key = legacy_raw.as_deref().map(parse_key).transpose()?;

        let keyring = if let Some(raw) = keyring_raw {
            let parsed = parse_keyring(&raw)?;
            let write_key_id = write_key_id.ok_or(VersionedMaterialError::KeyInvalid)?;
            if !parsed.contains_key(&write_key_id) {
                return Err(VersionedMaterialError::KeyInvalid);
            }
            parsed
        } else {
            if write_key_id.is_some() {
                return Err(VersionedMaterialError::KeyInvalid);
            }
            BTreeMap::new()
        };

        if legacy_key.is_none() && keyring.is_empty() {
            return Err(VersionedMaterialError::KeyInvalid);
        }

        Ok(Self {
            legacy_key,
            keyring,
            configuration_valid: true,
        })
    }

    pub fn reveal(&self, stored: &str) -> Result<String, VersionedMaterialError> {
        if stored.is_empty() {
            return Ok(String::new());
        }
        if !self.configuration_valid {
            return Err(VersionedMaterialError::KeyInvalid);
        }

        let (key, encoded, aad) = if let Some(remainder) = stored.strip_prefix("enc:v2:") {
            let (key_id, encoded) = remainder
                .split_once(':')
                .filter(|(key_id, encoded)| !key_id.is_empty() && !encoded.is_empty())
                .ok_or(VersionedMaterialError::EnvelopeInvalid)?;
            let key = self
                .keyring
                .get(key_id)
                .ok_or(VersionedMaterialError::KeyInvalid)?;
            let prefix_len = "enc:v2:".len() + key_id.len() + 1;
            (key, encoded, &stored.as_bytes()[..prefix_len])
        } else if let Some(encoded) = stored.strip_prefix("enc:v1:") {
            let key = self
                .legacy_key
                .as_ref()
                .ok_or(VersionedMaterialError::KeyInvalid)?;
            (key, encoded, &[][..])
        } else if stored.starts_with("enc:v") && stored["enc:v".len()..].contains(':') {
            return Err(VersionedMaterialError::EnvelopeInvalid);
        } else if let Some(encoded) = stored.strip_prefix("enc:") {
            let key = self
                .legacy_key
                .as_ref()
                .ok_or(VersionedMaterialError::KeyInvalid)?;
            (key, encoded, &[][..])
        } else {
            return Err(VersionedMaterialError::EnvelopeInvalid);
        };

        let raw = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|_| VersionedMaterialError::EnvelopeInvalid)?;
        if raw.len() < 28 {
            return Err(VersionedMaterialError::EnvelopeInvalid);
        }
        let (nonce_bytes, ciphertext) = raw.split_at(12);
        let cipher =
            Aes256Gcm::new_from_slice(key).map_err(|_| VersionedMaterialError::KeyInvalid)?;
        let plaintext = cipher
            .decrypt(
                Nonce::from_slice(nonce_bytes),
                Payload {
                    msg: ciphertext,
                    aad,
                },
            )
            .map_err(|_| VersionedMaterialError::EnvelopeInvalid)?;
        String::from_utf8(plaintext).map_err(|_| VersionedMaterialError::EnvelopeInvalid)
    }

    pub(crate) fn with_key(key: [u8; 32]) -> Self {
        Self {
            legacy_key: Some(key),
            keyring: BTreeMap::new(),
            configuration_valid: true,
        }
    }

    #[cfg(test)]
    pub(crate) fn with_keyring(
        legacy_key: Option<[u8; 32]>,
        keyring: BTreeMap<String, [u8; 32]>,
    ) -> Self {
        Self {
            legacy_key,
            keyring,
            configuration_valid: true,
        }
    }

    #[cfg(test)]
    pub fn without_key() -> Self {
        Self {
            legacy_key: None,
            keyring: BTreeMap::new(),
            configuration_valid: false,
        }
    }
}

fn parse_keyring(raw: &str) -> Result<BTreeMap<String, [u8; 32]>, VersionedMaterialError> {
    let values: BTreeMap<String, String> =
        serde_json::from_str(raw).map_err(|_| VersionedMaterialError::KeyInvalid)?;
    if values.is_empty() {
        return Err(VersionedMaterialError::KeyInvalid);
    }

    values
        .into_iter()
        .map(|(key_id, raw_key)| {
            if !valid_key_id(&key_id) {
                return Err(VersionedMaterialError::KeyInvalid);
            }
            Ok((key_id, parse_key(&raw_key)?))
        })
        .collect()
}

fn valid_key_id(key_id: &str) -> bool {
    !key_id.is_empty()
        && key_id.len() <= 128
        && key_id.as_bytes()[0].is_ascii_alphanumeric()
        && key_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn parse_key(raw: &str) -> Result<[u8; 32], VersionedMaterialError> {
    let bytes = hex::decode(raw)
        .or_else(|_| base64::engine::general_purpose::STANDARD.decode(raw))
        .map_err(|_| VersionedMaterialError::KeyInvalid)?;
    bytes
        .try_into()
        .map_err(|_| VersionedMaterialError::KeyInvalid)
}

fn canary_plaintext(key_id: &str) -> String {
    format!("joysafeter-credential-encryption-canary:{key_id}")
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::{VersionedMaterialError, VersionedMaterialProtector};

    const TEST_KEY: [u8; 32] = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
        25, 26, 27, 28, 29, 30, 31,
    ];

    #[test]
    fn legacy_and_v1_envelopes_reveal_but_plaintext_and_unknown_versions_fail() {
        let protector = VersionedMaterialProtector::with_key(TEST_KEY);
        let v1 = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";
        let legacy = format!("enc:{}", v1.strip_prefix("enc:v1:").unwrap());

        assert_eq!(protector.reveal(v1).unwrap(), "hello-world");
        assert_eq!(protector.reveal(&legacy).unwrap(), "hello-world");
        assert_eq!(
            protector.reveal("plaintext"),
            Err(VersionedMaterialError::EnvelopeInvalid)
        );
        assert_eq!(
            protector.reveal("enc:v3:unsupported"),
            Err(VersionedMaterialError::EnvelopeInvalid)
        );
    }

    #[test]
    fn v2_envelope_uses_embedded_key_id() {
        let protector = VersionedMaterialProtector::with_keyring(
            None,
            BTreeMap::from([("active-2026-08".to_string(), TEST_KEY)]),
        );

        assert_eq!(
            protector
                .reveal(
                    "enc:v2:active-2026-08:XPCBUDirm4X13pqPmVYdF8XL0Lo+i11bsQM8txwse5sTW1o2UMAe"
                )
                .unwrap(),
            "hello-world"
        );
        assert_eq!(
            protector.reveal("enc:v2:retired:AA=="),
            Err(VersionedMaterialError::KeyInvalid)
        );
    }

    #[test]
    fn v2_envelope_authenticates_embedded_key_id() {
        let protector = VersionedMaterialProtector::with_keyring(
            None,
            BTreeMap::from([
                ("active-2026-08".to_string(), TEST_KEY),
                ("alias-2026-08".to_string(), TEST_KEY),
            ]),
        );
        let relabeled = "enc:v2:alias-2026-08:XPCBUDirm4X13pqPmVYdF8XL0Lo+i11bsQM8txwse5sTW1o2UMAe";

        assert_eq!(
            protector.reveal(relabeled),
            Err(VersionedMaterialError::EnvelopeInvalid)
        );
    }

    #[test]
    fn pre_release_v2_envelope_without_authenticated_prefix_is_rejected() {
        let protector = VersionedMaterialProtector::with_keyring(
            None,
            BTreeMap::from([("active-2026-08".to_string(), TEST_KEY)]),
        );
        let unauthenticated =
            "enc:v2:active-2026-08:XPCBUDirm4X13pqPmVYdF8XL0Lo+i131xweAbmv4iU7fD8/fXnmD";

        assert_eq!(
            protector.reveal(unauthenticated),
            Err(VersionedMaterialError::EnvelopeInvalid)
        );
    }

    #[test]
    fn envelope_inventory_requires_every_referenced_read_key() {
        let protector = VersionedMaterialProtector::with_keyring(
            None,
            BTreeMap::from([("active-2026-08".to_string(), TEST_KEY)]),
        );

        assert_eq!(
            protector.validate_envelope_reference("enc:v1"),
            Err(VersionedMaterialError::KeyInvalid)
        );
        assert_eq!(
            protector.validate_envelope_reference("enc:v2:previous-2026-07"),
            Err(VersionedMaterialError::KeyInvalid)
        );
        assert_eq!(
            protector.validate_envelope_reference("invalid-or-plaintext"),
            Err(VersionedMaterialError::EnvelopeInvalid)
        );
        assert_eq!(
            protector.validate_envelope_reference("enc:v2:active-2026-08"),
            Ok(())
        );
    }
}
