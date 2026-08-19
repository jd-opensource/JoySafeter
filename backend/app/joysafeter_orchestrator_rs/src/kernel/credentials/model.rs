use std::fmt;

use super::error::CredentialRuntimeError;
use super::record::{CredentialKind, CredentialMaterial, CredentialRecord};

#[derive(Clone)]
pub struct ResolvedModelCredential {
    pub protocol_id: String,
    pub credential_profile_id: String,
    pub default_base_url: Option<String>,
    pub base_url_key: String,
    pub model_key: Option<String>,
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
            required_material_fields: self.required_material_fields.clone(),
            required_material_alternatives: self.required_material_alternatives.clone(),
        }
    }
}

pub fn resolve_model_credential(
    record: &CredentialRecord,
    engine_kind: &str,
) -> Result<ResolvedModelCredential, CredentialRuntimeError> {
    if record.kind != CredentialKind::Model {
        return Err(CredentialRuntimeError::KindMismatch);
    }
    let binding = crate::kernel::llm_catalog::validate_runtime_secret(
        engine_kind,
        record.kind.as_str(),
        record.provider.as_deref(),
        record.protocol.as_deref(),
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
        required_material_fields: binding.required_material_fields,
        required_material_alternatives: binding.required_material_alternatives,
        material: record.material.clone(),
    })
}
