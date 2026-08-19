use thiserror::Error;

use crate::kernel::sensitive_material::legacy_v1::{
    LegacyV1MaterialError, LegacyV1MaterialProtector,
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

#[derive(Clone)]
pub struct TaskIdentityMaterialAdapter {
    protector: LegacyV1MaterialProtector,
}

impl TaskIdentityMaterialAdapter {
    pub fn from_env() -> Self {
        Self {
            protector: LegacyV1MaterialProtector::from_env(),
        }
    }

    pub fn reveal(&self, encrypted_material: &str) -> Result<String, TaskIdentityMaterialError> {
        let material = self
            .protector
            .reveal(encrypted_material)
            .map_err(|error| match error {
                LegacyV1MaterialError::KeyInvalid => TaskIdentityMaterialError::KeyInvalid,
                LegacyV1MaterialError::EnvelopeInvalid => {
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
            protector: LegacyV1MaterialProtector::with_key(key),
        }
    }

    #[cfg(test)]
    pub fn without_key() -> Self {
        Self {
            protector: LegacyV1MaterialProtector::without_key(),
        }
    }
}
