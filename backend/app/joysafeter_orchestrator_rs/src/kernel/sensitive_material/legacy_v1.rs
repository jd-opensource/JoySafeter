use std::sync::OnceLock;

use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use base64::Engine as _;
use thiserror::Error;

#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum LegacyV1MaterialError {
    #[error("material encryption key is missing or invalid")]
    KeyInvalid,
    #[error("material envelope is unsupported or malformed")]
    EnvelopeInvalid,
}

#[derive(Clone)]
pub struct LegacyV1MaterialProtector {
    key: Option<[u8; 32]>,
}

impl LegacyV1MaterialProtector {
    pub fn validate_env_key() -> Result<(), LegacyV1MaterialError> {
        let raw = std::env::var("JOYSAFETER_VAULT_ENCRYPTION_KEY")
            .map_err(|_| LegacyV1MaterialError::KeyInvalid)?;
        parse_key(&raw).ok_or(LegacyV1MaterialError::KeyInvalid)?;
        Ok(())
    }

    pub fn from_env() -> Self {
        static KEY: OnceLock<Option<[u8; 32]>> = OnceLock::new();
        let key = *KEY.get_or_init(|| {
            std::env::var("JOYSAFETER_VAULT_ENCRYPTION_KEY")
                .ok()
                .and_then(|raw| parse_key(&raw))
        });
        Self { key }
    }

    pub fn reveal(&self, stored: &str) -> Result<String, LegacyV1MaterialError> {
        if stored.is_empty() {
            return Ok(String::new());
        }
        let encoded = if let Some(encoded) = stored.strip_prefix("enc:v1:") {
            encoded
        } else if stored.starts_with("enc:v") && stored["enc:v".len()..].contains(':') {
            return Err(LegacyV1MaterialError::EnvelopeInvalid);
        } else if let Some(encoded) = stored.strip_prefix("enc:") {
            encoded
        } else {
            return Err(LegacyV1MaterialError::EnvelopeInvalid);
        };
        let key = self.key.ok_or(LegacyV1MaterialError::KeyInvalid)?;
        let raw = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|_| LegacyV1MaterialError::EnvelopeInvalid)?;
        if raw.len() < 28 {
            return Err(LegacyV1MaterialError::EnvelopeInvalid);
        }
        let (nonce_bytes, ciphertext) = raw.split_at(12);
        let cipher =
            Aes256Gcm::new_from_slice(&key).map_err(|_| LegacyV1MaterialError::KeyInvalid)?;
        let plaintext = cipher
            .decrypt(Nonce::from_slice(nonce_bytes), ciphertext)
            .map_err(|_| LegacyV1MaterialError::EnvelopeInvalid)?;
        String::from_utf8(plaintext).map_err(|_| LegacyV1MaterialError::EnvelopeInvalid)
    }

    pub(crate) fn with_key(key: [u8; 32]) -> Self {
        Self { key: Some(key) }
    }

    #[cfg(test)]
    pub fn without_key() -> Self {
        Self { key: None }
    }
}

fn parse_key(raw: &str) -> Option<[u8; 32]> {
    let bytes = hex::decode(raw)
        .or_else(|_| base64::engine::general_purpose::STANDARD.decode(raw))
        .ok()?;
    bytes.try_into().ok()
}

#[cfg(test)]
mod tests {
    use super::{LegacyV1MaterialError, LegacyV1MaterialProtector};

    #[test]
    fn legacy_and_v1_envelopes_reveal_but_plaintext_and_unknown_versions_fail() {
        let protector = LegacyV1MaterialProtector::with_key([
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
            24, 25, 26, 27, 28, 29, 30, 31,
        ]);
        let v1 = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";
        let legacy = format!("enc:{}", v1.strip_prefix("enc:v1:").unwrap());

        assert_eq!(protector.reveal(v1).unwrap(), "hello-world");
        assert_eq!(protector.reveal(&legacy).unwrap(), "hello-world");
        assert_eq!(
            protector.reveal("plaintext"),
            Err(LegacyV1MaterialError::EnvelopeInvalid)
        );
        assert_eq!(
            protector.reveal("enc:v2:unsupported"),
            Err(LegacyV1MaterialError::EnvelopeInvalid)
        );
    }
}
