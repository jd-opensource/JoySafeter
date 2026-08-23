use std::collections::{BTreeMap, BTreeSet};

use serde_json::Value;

use crate::kernel::sensitive_material::versioned::VersionedMaterialProtector;

use super::error::CredentialRuntimeError;
use super::record::CredentialMaterial;

#[derive(Clone)]
pub struct ManagedCredentialMaterialAdapter {
    protector: VersionedMaterialProtector,
}

#[derive(Debug, Clone, Copy)]
pub enum MaterialFieldSelection<'a> {
    All,
    Only(&'a BTreeSet<String>),
}

impl ManagedCredentialMaterialAdapter {
    pub fn from_env() -> Self {
        Self {
            protector: VersionedMaterialProtector::from_env(),
        }
    }

    pub fn from_key(key: [u8; 32]) -> Self {
        Self {
            protector: VersionedMaterialProtector::with_key(key),
        }
    }

    pub fn reveal(&self, stored: &Value) -> Result<CredentialMaterial, CredentialRuntimeError> {
        self.reveal_fields(stored, MaterialFieldSelection::All)
    }

    pub fn reveal_fields(
        &self,
        stored: &Value,
        selection: MaterialFieldSelection<'_>,
    ) -> Result<CredentialMaterial, CredentialRuntimeError> {
        let object = stored
            .as_object()
            .ok_or(CredentialRuntimeError::CorruptRecord)?;
        let mut values = BTreeMap::new();
        let selected = match selection {
            MaterialFieldSelection::All => object.iter().collect::<Vec<_>>(),
            MaterialFieldSelection::Only(fields) => fields
                .iter()
                .map(|field| {
                    object
                        .get_key_value(field)
                        .ok_or(CredentialRuntimeError::FieldMissing)
                })
                .collect::<Result<Vec<_>, _>>()?,
        };
        for (field, value) in selected {
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

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use serde_json::json;

    use super::{ManagedCredentialMaterialAdapter, MaterialFieldSelection};
    use crate::kernel::credentials::error::CredentialRuntimeError;

    const TEST_KEY: [u8; 32] = [
        0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24,
        25, 26, 27, 28, 29, 30, 31,
    ];
    const HELLO_WORLD: &str = "enc:v1:VzniG9ulG62e3VZZD1jujN8lxiW1h/6a0Hdj1jIlJC/Wl9Rvvk7D";

    #[test]
    fn field_scoped_reveal_does_not_decrypt_unrequested_fields() {
        let adapter = ManagedCredentialMaterialAdapter::from_key(TEST_KEY);
        let requested = BTreeSet::from(["required".to_string()]);

        let material = adapter
            .reveal_fields(
                &json!({"required": HELLO_WORLD, "unrelated": "invalid-envelope"}),
                MaterialFieldSelection::Only(&requested),
            )
            .expect("unrequested invalid ciphertext must not be decrypted");

        assert_eq!(material.require("required").unwrap(), "hello-world");
        assert_eq!(
            material.require("unrelated"),
            Err(CredentialRuntimeError::FieldMissing)
        );
    }

    #[test]
    fn field_scoped_reveal_rejects_missing_requested_field() {
        let adapter = ManagedCredentialMaterialAdapter::from_key(TEST_KEY);
        let requested = BTreeSet::from(["missing".to_string()]);

        assert_eq!(
            adapter.reveal_fields(
                &json!({"required": HELLO_WORLD}),
                MaterialFieldSelection::Only(&requested),
            ),
            Err(CredentialRuntimeError::FieldMissing)
        );
    }
}
