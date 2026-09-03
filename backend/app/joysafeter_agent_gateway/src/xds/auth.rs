use std::collections::{BTreeMap, HashSet};
use std::fmt;

use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;
use tonic::{Request, Status};

pub const XDS_AUTH_HEADER: &str = "x-joysafeter-xds-token";
const MAX_KEYRING_ENTRIES: usize = 4;
const MIN_TOKEN_BYTES: usize = 32;
const MAX_TOKEN_BYTES: usize = 512;

#[derive(Clone)]
struct XdsAuthKey {
    key_id: String,
    digest: [u8; 32],
}

#[derive(Clone)]
pub struct XdsAuthKeyring {
    keys: Vec<XdsAuthKey>,
}

impl fmt::Debug for XdsAuthKeyring {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("XdsAuthKeyring")
            .field("key_count", &self.keys.len())
            .finish()
    }
}

impl XdsAuthKeyring {
    pub fn parse(raw: &str, write_key_id: &str) -> anyhow::Result<Self> {
        let values: BTreeMap<String, String> = serde_json::from_str(raw)
            .map_err(|_| anyhow::anyhow!("JOYSAFETER_XDS_AUTH_KEYRING must be a JSON object"))?;
        if values.is_empty() || values.len() > MAX_KEYRING_ENTRIES {
            anyhow::bail!(
                "JOYSAFETER_XDS_AUTH_KEYRING must contain between 1 and {MAX_KEYRING_ENTRIES} entries"
            );
        }
        let write_key_id = write_key_id.trim();
        if write_key_id.is_empty() {
            anyhow::bail!("JOYSAFETER_XDS_AUTH_WRITE_KEY_ID must not be empty");
        }

        let mut seen_tokens = HashSet::with_capacity(values.len());
        let mut keys = Vec::with_capacity(values.len());
        let mut write_key_index = None;
        for (key_id, token) in values {
            let key_id = key_id.trim();
            let token = token.trim();
            if key_id.is_empty() || key_id.len() > 64 {
                anyhow::bail!("JOYSAFETER_XDS_AUTH_KEYRING contains an invalid key id");
            }
            if !(MIN_TOKEN_BYTES..=MAX_TOKEN_BYTES).contains(&token.len()) {
                anyhow::bail!(
                    "JOYSAFETER_XDS_AUTH_KEYRING token values must be between {MIN_TOKEN_BYTES} and {MAX_TOKEN_BYTES} bytes"
                );
            }
            if !token.bytes().all(|byte| {
                byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~')
            }) {
                anyhow::bail!(
                    "JOYSAFETER_XDS_AUTH_KEYRING token values must use a URL-safe ASCII alphabet"
                );
            }
            let digest: [u8; 32] = Sha256::digest(token.as_bytes()).into();
            if !seen_tokens.insert(digest) {
                anyhow::bail!("JOYSAFETER_XDS_AUTH_KEYRING token values must be unique");
            }
            if key_id == write_key_id {
                write_key_index = Some(keys.len());
            }
            keys.push(XdsAuthKey {
                key_id: key_id.to_string(),
                digest,
            });
        }

        write_key_index.ok_or_else(|| {
            anyhow::anyhow!(
                "JOYSAFETER_XDS_AUTH_WRITE_KEY_ID must reference an entry in JOYSAFETER_XDS_AUTH_KEYRING"
            )
        })?;
        Ok(Self { keys })
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct XdsClientPrincipal {
    key_id: String,
}

impl fmt::Debug for XdsClientPrincipal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("XdsClientPrincipal(<redacted>)")
    }
}

impl XdsClientPrincipal {
    pub fn key_id(&self) -> &str {
        &self.key_id
    }
}

pub trait XdsClientAuthenticator: Send + Sync + 'static {
    #[allow(clippy::result_large_err)] // tonic interceptors require tonic::Status.
    fn authenticate(&self, request: &Request<()>) -> Result<XdsClientPrincipal, Status>;
}

#[derive(Clone, Debug)]
pub struct SharedTokenAuthenticator {
    keyring: XdsAuthKeyring,
}

impl SharedTokenAuthenticator {
    pub fn new(keyring: XdsAuthKeyring) -> Self {
        Self { keyring }
    }

    #[allow(clippy::result_large_err)] // Public helper mirrors tonic's interceptor contract.
    pub fn authenticate_value(&self, token: Option<&str>) -> Result<XdsClientPrincipal, Status> {
        let token = token.ok_or_else(authentication_failed)?;
        let candidate: [u8; 32] = Sha256::digest(token.as_bytes()).into();
        let mut matched_key_id = None;
        for key in &self.keyring.keys {
            if bool::from(candidate.ct_eq(&key.digest)) {
                matched_key_id = Some(key.key_id.clone());
            }
        }
        matched_key_id
            .map(|key_id| XdsClientPrincipal { key_id })
            .ok_or_else(authentication_failed)
    }
}

impl XdsClientAuthenticator for SharedTokenAuthenticator {
    #[allow(clippy::result_large_err)] // tonic interceptors require tonic::Status.
    fn authenticate(&self, request: &Request<()>) -> Result<XdsClientPrincipal, Status> {
        let token = request
            .metadata()
            .get(XDS_AUTH_HEADER)
            .and_then(|value| value.to_str().ok());
        self.authenticate_value(token)
    }
}

fn authentication_failed() -> Status {
    Status::unauthenticated("xDS client authentication failed")
}

#[cfg(test)]
#[path = "../../tests/unit/xds/auth_test.rs"]
mod tests;
