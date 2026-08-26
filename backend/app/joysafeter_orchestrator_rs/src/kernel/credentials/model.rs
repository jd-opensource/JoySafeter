use std::collections::BTreeSet;
use std::fmt;

use super::error::CredentialRuntimeError;
use super::record::{
    CredentialKind, CredentialMaterial, CredentialMetadataRecord, CredentialRecord,
};

#[derive(Clone)]
pub struct ResolvedModelCredential {
    pub protocol_id: String,
    pub credential_profile_id: String,
    pub default_base_url: Option<String>,
    pub base_url_key: String,
    pub model_key: Option<String>,
    pub material_fields: Vec<String>,
    pub required_material_fields: Vec<String>,
    pub required_material_alternatives: Vec<Vec<String>>,
    pub material: CredentialMaterial,
}

impl fmt::Debug for ResolvedModelCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedModelCredential")
            .field("protocol_id", &self.protocol_id)
            .field("credential_profile_id", &self.credential_profile_id)
            .field("default_base_url", &self.default_base_url)
            .field("base_url_key", &self.base_url_key)
            .field("model_key", &self.model_key)
            .field("material_fields", &self.material_fields)
            .field("required_material_fields", &self.required_material_fields)
            .field(
                "required_material_alternatives",
                &self.required_material_alternatives,
            )
            .field("material", &self.material)
            .finish()
    }
}

impl ResolvedModelCredential {
    pub fn runtime_binding(&self) -> crate::kernel::llm_catalog::RuntimeCredentialBinding {
        crate::kernel::llm_catalog::RuntimeCredentialBinding {
            protocol_id: self.protocol_id.clone(),
            credential_profile_id: self.credential_profile_id.clone(),
            default_base_url: self.default_base_url.clone(),
            base_url_key: self.base_url_key.clone(),
            model_key: self.model_key.clone(),
            material_fields: self.material_fields.clone(),
            required_material_fields: self.required_material_fields.clone(),
            required_material_alternatives: self.required_material_alternatives.clone(),
        }
    }
}

pub fn resolve_model_credential(
    record: &CredentialRecord,
    engine_kind: &str,
) -> Result<ResolvedModelCredential, CredentialRuntimeError> {
    let binding = validate_model_binding(
        record.kind,
        record.provider.as_deref(),
        record.protocol.as_deref(),
        engine_kind,
    )?;
    for field in &binding.required_material_fields {
        record.material.require(field)?;
    }
    for alternatives in &binding.required_material_alternatives {
        if !alternatives
            .iter()
            .any(|field| record.material.require(field).is_ok())
        {
            return Err(CredentialRuntimeError::FieldMissing);
        }
    }
    Ok(ResolvedModelCredential {
        protocol_id: binding.protocol_id,
        credential_profile_id: binding.credential_profile_id,
        default_base_url: binding.default_base_url,
        base_url_key: binding.base_url_key,
        model_key: binding.model_key,
        material_fields: binding.material_fields,
        required_material_fields: binding.required_material_fields,
        required_material_alternatives: binding.required_material_alternatives,
        material: record.material.clone(),
    })
}

pub fn validate_model_credential_metadata(
    record: &CredentialMetadataRecord,
    engine_kind: &str,
) -> Result<crate::kernel::llm_catalog::RuntimeCredentialBinding, CredentialRuntimeError> {
    let binding = validate_model_binding(
        record.kind,
        record.provider.as_deref(),
        record.protocol.as_deref(),
        engine_kind,
    )?;
    for field in &binding.required_material_fields {
        if !record.material_fields.contains(field) {
            return Err(CredentialRuntimeError::FieldMissing);
        }
    }
    for alternatives in &binding.required_material_alternatives {
        if !alternatives
            .iter()
            .any(|field| record.material_fields.contains(field))
        {
            return Err(CredentialRuntimeError::FieldMissing);
        }
    }
    Ok(binding)
}

pub fn model_material_fields(
    record: &CredentialMetadataRecord,
    engine_kind: &str,
) -> Result<BTreeSet<String>, CredentialRuntimeError> {
    let binding = validate_model_credential_metadata(record, engine_kind)?;
    Ok(binding
        .material_fields
        .into_iter()
        .filter(|field| record.material_fields.contains(field))
        .collect())
}

fn validate_model_binding(
    kind: CredentialKind,
    provider: Option<&str>,
    protocol: Option<&str>,
    engine_kind: &str,
) -> Result<crate::kernel::llm_catalog::RuntimeCredentialBinding, CredentialRuntimeError> {
    if kind != CredentialKind::Model {
        return Err(CredentialRuntimeError::KindMismatch);
    }
    let binding = crate::kernel::llm_catalog::validate_runtime_secret(
        engine_kind,
        kind.as_str(),
        provider,
        protocol,
    )
    .map_err(|error| match error {
        crate::kernel::llm_catalog::LlmCatalogError::SecretKindInvalid { .. } => {
            CredentialRuntimeError::KindMismatch
        }
        crate::kernel::llm_catalog::LlmCatalogError::ProviderRequired
        | crate::kernel::llm_catalog::LlmCatalogError::ProtocolRequired => {
            CredentialRuntimeError::FieldMissing
        }
        _ => CredentialRuntimeError::CorruptRecord,
    })?;
    Ok(binding)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use uuid::Uuid;

    use super::model_material_fields;
    use crate::ids::CredentialId;
    use crate::ids::ProjectId;
    use crate::kernel::credentials::record::{CredentialKind, CredentialMetadataRecord};

    #[test]
    fn model_material_fields_include_catalog_fields_and_exclude_unknown_fields() {
        let metadata = CredentialMetadataRecord {
            id: CredentialId::from_uuid(Uuid::now_v7()),
            project_id: ProjectId::from_uuid(uuid::Uuid::from_u128(1)),
            kind: CredentialKind::Model,
            provider: Some("anthropic".to_string()),
            protocol: Some("anthropic_messages".to_string()),
            group_id: None,
            server_url: None,
            normalized_server_url: None,
            auth_scheme: None,
            material_fields: BTreeSet::from([
                "ANTHROPIC_API_KEY".to_string(),
                "ANTHROPIC_BASE_URL".to_string(),
                "UNRELATED".to_string(),
            ]),
        };

        assert_eq!(
            model_material_fields(&metadata, "claude").unwrap(),
            BTreeSet::from([
                "ANTHROPIC_API_KEY".to_string(),
                "ANTHROPIC_BASE_URL".to_string(),
            ])
        );
    }
}
