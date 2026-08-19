use crate::kernel::credentials::error::CredentialRuntimeError;
use crate::kernel::sensitive_material::legacy_v1::LegacyV1MaterialProtector;

#[derive(Clone)]
pub struct RepositoryAccessMaterialAdapter {
    protector: LegacyV1MaterialProtector,
}

impl RepositoryAccessMaterialAdapter {
    pub fn from_env() -> Self {
        Self {
            protector: LegacyV1MaterialProtector::from_env(),
        }
    }

    pub fn reveal_optional(
        &self,
        encrypted_material: &str,
    ) -> Result<Option<String>, CredentialRuntimeError> {
        if encrypted_material.is_empty() {
            return Ok(None);
        }
        let material = self
            .protector
            .reveal(encrypted_material)
            .map_err(|_| CredentialRuntimeError::EnvelopeInvalid)?;
        if material.is_empty() {
            Ok(None)
        } else {
            Ok(Some(material))
        }
    }
}
