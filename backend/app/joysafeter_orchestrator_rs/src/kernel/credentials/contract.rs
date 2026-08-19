use std::collections::HashMap;
use std::sync::LazyLock;

use serde::Deserialize;

use super::error::CredentialRuntimeError;

const RAW_CREDENTIAL_DOMAIN_CONTRACT: &str =
    include_str!("../../../../../contracts/credential_domain_contract.json");
const RAW_CREDENTIAL_REFERENCE_CONTRACT: &str =
    include_str!("../../../../../contracts/credential_reference_contract.json");

static CREDENTIAL_CONTRACT: LazyLock<CredentialContract> = LazyLock::new(|| {
    serde_json::from_str(RAW_CREDENTIAL_DOMAIN_CONTRACT)
        .expect("embedded credential domain contract must be valid")
});
static CREDENTIAL_REFERENCE_CONTRACT: LazyLock<CredentialReferenceContract> = LazyLock::new(|| {
    serde_json::from_str(RAW_CREDENTIAL_REFERENCE_CONTRACT)
        .expect("embedded credential reference contract must be valid")
});

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialContract {
    #[allow(dead_code)]
    contract_version: u8,
    credential_kinds: Vec<String>,
    auth_schemes: Vec<String>,
    auth_scheme_aliases: HashMap<String, String>,
    disabled_auth_schemes: Vec<String>,
    runtime_errors: Vec<String>,
    #[allow(dead_code)]
    encryption_envelope: String,
}

impl CredentialContract {
    pub fn embedded() -> &'static Self {
        &CREDENTIAL_CONTRACT
    }

    pub fn is_kind(&self, value: &str) -> bool {
        self.credential_kinds.iter().any(|kind| kind == value)
    }

    pub fn is_model_kind(&self, value: &str) -> bool {
        self.credential_kinds
            .first()
            .is_some_and(|kind| kind == value)
    }

    pub fn has_runtime_error(&self, value: &str) -> bool {
        self.runtime_errors.iter().any(|error| error == value)
    }

    fn canonical_auth_scheme(
        &'static self,
        raw: &str,
    ) -> Result<&'static str, CredentialRuntimeError> {
        if let Some(scheme) = self
            .auth_schemes
            .iter()
            .find(|scheme| scheme.as_str() == raw)
        {
            return Ok(scheme);
        }
        if let Some(scheme) = self.auth_scheme_aliases.get(raw) {
            return Ok(scheme);
        }
        if self
            .disabled_auth_schemes
            .iter()
            .any(|scheme| scheme == raw)
        {
            return Err(CredentialRuntimeError::UnsupportedScheme);
        }
        Err(CredentialRuntimeError::CorruptRecord)
    }
}

pub fn canonical_auth_scheme(raw: &str) -> Result<&'static str, CredentialRuntimeError> {
    CredentialContract::embedded().canonical_auth_scheme(raw)
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialReferenceContract {
    #[allow(dead_code)]
    contract_version: u8,
    #[allow(dead_code)]
    snapshot_schemas: HashMap<String, Option<String>>,
    #[allow(dead_code)]
    canonical_reference_keys: Vec<String>,
    #[allow(dead_code)]
    legacy_aliases: HashMap<String, Vec<String>>,
    #[allow(dead_code)]
    legacy_decoder_keys: Vec<String>,
    normalization: CredentialReferenceNormalization,
    fixture_matrix: CredentialReferenceFixtureMatrix,
    reference_paths: Vec<CredentialReferencePath>,
    #[allow(dead_code)]
    consumer_surfaces: Vec<String>,
    error_categories: HashMap<String, String>,
    test_vectors: Vec<serde_json::Value>,
    parity_vectors: Vec<CredentialReferenceParityVector>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialReferenceNormalization {
    inject_type: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialReferenceFixtureMatrix {
    pub generator: String,
    pub credential_id: String,
    pub secondary_credential_id: String,
    pub credential_field: String,
    pub inject_type: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialReferencePath {
    pub schemas: Vec<String>,
    pub document: String,
    pub path: String,
    pub value_kind: String,
    pub surface: String,
    pub scanner_fixture: String,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CredentialReferenceParityVector {
    pub name: String,
    pub category: String,
    pub document: String,
    pub input: serde_json::Value,
    pub result: String,
    pub expected_credential_ids: Option<Vec<String>>,
    pub expected_inject_types: Option<Vec<String>>,
}

impl CredentialReferenceContract {
    pub fn embedded() -> &'static Self {
        &CREDENTIAL_REFERENCE_CONTRACT
    }

    pub fn error_category(&self, value: &str) -> Option<&str> {
        self.error_categories.get(value).map(String::as_str)
    }

    pub fn snapshot_schema_name(&self, value: Option<&str>) -> Option<&str> {
        self.snapshot_schemas
            .iter()
            .find_map(|(name, schema)| (schema.as_deref() == value).then_some(name.as_str()))
    }

    pub fn snapshot_schema_value(&self, name: &str) -> Option<&str> {
        self.snapshot_schemas.get(name).and_then(Option::as_deref)
    }

    pub fn inject_type_normalization(&self) -> &str {
        &self.normalization.inject_type
    }

    pub fn reference_paths(&self) -> &[CredentialReferencePath] {
        &self.reference_paths
    }

    pub fn is_registered_reference_key(&self, key: &str) -> bool {
        self.canonical_reference_keys
            .iter()
            .any(|candidate| candidate == key)
            || self
                .legacy_decoder_keys
                .iter()
                .any(|candidate| candidate == key)
            || self
                .legacy_aliases
                .values()
                .flatten()
                .any(|candidate| candidate == key)
            || self.reference_paths.iter().any(|entry| {
                entry
                    .path
                    .trim_start_matches("$.")
                    .split('.')
                    .map(|segment| segment.trim_end_matches("[*]"))
                    .any(|segment| segment == key)
            })
    }

    #[cfg(test)]
    pub fn fixture_matrix(&self) -> &CredentialReferenceFixtureMatrix {
        &self.fixture_matrix
    }

    #[cfg(test)]
    pub fn parity_vectors(&self) -> &[CredentialReferenceParityVector] {
        &self.parity_vectors
    }

    #[cfg(test)]
    pub fn test_vectors(&self) -> &[serde_json::Value] {
        &self.test_vectors
    }
}

#[cfg(test)]
mod tests {
    use super::{canonical_auth_scheme, CredentialContract, CredentialReferenceContract};
    use crate::kernel::credentials::error::CredentialRuntimeError;

    #[test]
    fn db_model_kind_is_valid() {
        let contract = CredentialContract::embedded();

        assert!(contract.is_kind("model"));
        assert!(!contract.is_kind("llm"));
        assert!(contract.is_model_kind("model"));
    }

    #[test]
    fn canonical_auth_scheme_uses_the_embedded_contract() {
        assert_eq!(canonical_auth_scheme("static_bearer"), Ok("static_bearer"));
        assert_eq!(canonical_auth_scheme("bearer"), Ok("static_bearer"));
        assert_eq!(
            canonical_auth_scheme("oauth"),
            Err(CredentialRuntimeError::UnsupportedScheme)
        );
        assert_eq!(
            canonical_auth_scheme("mcp_oauth"),
            Err(CredentialRuntimeError::UnsupportedScheme)
        );
        assert_eq!(
            canonical_auth_scheme("unknown"),
            Err(CredentialRuntimeError::CorruptRecord)
        );
    }

    #[test]
    fn runtime_errors_are_validated_against_the_embedded_contract() {
        let contract = CredentialContract::embedded();

        assert!(CredentialRuntimeError::ALL
            .into_iter()
            .all(|error| contract.has_runtime_error(error.contract_code())));
    }

    #[test]
    fn reference_contract_fails_unknown_explicit_schema_as_corrupt() {
        assert_eq!(
            CredentialReferenceContract::embedded().error_category("unknown_explicit_schema"),
            Some("corrupt_record")
        );
    }
}
