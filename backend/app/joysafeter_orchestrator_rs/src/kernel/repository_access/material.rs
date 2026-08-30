use crate::kernel::credentials::error::CredentialRuntimeError;
use crate::kernel::sensitive_material::versioned::VersionedMaterialProtector;

pub trait RepositoryAccessMaterial: Send + Sync {
    fn reveal_optional(
        &self,
        encrypted_material: &str,
    ) -> Result<Option<String>, CredentialRuntimeError>;
}

#[derive(Clone)]
pub struct RepositoryAccessMaterialAdapter {
    protector: VersionedMaterialProtector,
}

impl RepositoryAccessMaterialAdapter {
    pub fn from_env() -> Self {
        Self {
            protector: VersionedMaterialProtector::from_env(),
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

impl RepositoryAccessMaterial for RepositoryAccessMaterialAdapter {
    fn reveal_optional(
        &self,
        encrypted_material: &str,
    ) -> Result<Option<String>, CredentialRuntimeError> {
        RepositoryAccessMaterialAdapter::reveal_optional(self, encrypted_material)
    }
}
