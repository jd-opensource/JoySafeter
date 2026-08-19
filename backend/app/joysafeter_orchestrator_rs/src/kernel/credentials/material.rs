use std::collections::BTreeMap;

use serde_json::Value;

use crate::kernel::sensitive_material::legacy_v1::LegacyV1MaterialProtector;

use super::error::CredentialRuntimeError;
use super::record::CredentialMaterial;

#[derive(Clone)]
pub struct ManagedCredentialMaterialAdapter {
    protector: LegacyV1MaterialProtector,
}

impl ManagedCredentialMaterialAdapter {
    pub fn from_env() -> Self {
        Self {
            protector: LegacyV1MaterialProtector::from_env(),
        }
    }

    pub fn from_key(key: [u8; 32]) -> Self {
        Self {
            protector: LegacyV1MaterialProtector::with_key(key),
        }
    }

    pub fn reveal(&self, stored: &Value) -> Result<CredentialMaterial, CredentialRuntimeError> {
        let object = stored
            .as_object()
            .ok_or(CredentialRuntimeError::CorruptRecord)?;
        let mut values = BTreeMap::new();
        for (field, value) in object {
            let value = value
                .as_str()
                .ok_or(CredentialRuntimeError::CorruptRecord)?;
            let plaintext = self
                .protector
                .reveal(value)
                .map_err(|_| CredentialRuntimeError::EnvelopeInvalid)?;
            values.insert(field.clone(), plaintext);
        }
        Ok(CredentialMaterial::new(values))
    }
}
