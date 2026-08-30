use thiserror::Error;

use crate::kernel::sensitive_material::versioned::{
    VersionedMaterialError, VersionedMaterialProtector,
};

#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum TaskIdentityMaterialError {
    #[error("task identity material key is invalid")]
    KeyInvalid,
    #[error("task identity material envelope is invalid")]
    EnvelopeInvalid,
    #[error("task identity material is missing")]
    FieldMissing,
}

pub trait TaskIdentityMaterial: Send + Sync {
    fn reveal(&self, encrypted_material: &str) -> Result<String, TaskIdentityMaterialError>;
}

#[derive(Clone)]
pub struct TaskIdentityMaterialAdapter {
    protector: VersionedMaterialProtector,
}

impl TaskIdentityMaterialAdapter {
    pub fn from_env() -> Self {
        Self {
            protector: VersionedMaterialProtector::from_env(),
        }
    }

    pub fn reveal(&self, encrypted_material: &str) -> Result<String, TaskIdentityMaterialError> {
        let material = self
            .protector
            .reveal(encrypted_material)
            .map_err(|error| match error {
                VersionedMaterialError::KeyInvalid => TaskIdentityMaterialError::KeyInvalid,
                VersionedMaterialError::EnvelopeInvalid => {
                    TaskIdentityMaterialError::EnvelopeInvalid
                }
            })?;
        if material.is_empty() {
            return Err(TaskIdentityMaterialError::FieldMissing);
        }
        Ok(material)
    }

    #[cfg(test)]
    pub fn with_key(key: [u8; 32]) -> Self {
        Self {
            protector: VersionedMaterialProtector::with_key(key),
        }
    }

    #[cfg(test)]
    pub fn without_key() -> Self {
        Self {
            protector: VersionedMaterialProtector::without_key(),
        }
    }
}

impl TaskIdentityMaterial for TaskIdentityMaterialAdapter {
    fn reveal(&self, encrypted_material: &str) -> Result<String, TaskIdentityMaterialError> {
        TaskIdentityMaterialAdapter::reveal(self, encrypted_material)
    }
}
