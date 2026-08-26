use thiserror::Error;

use crate::ids::{CredentialId, ProjectId};

#[derive(Debug, Clone, Copy, Error, PartialEq, Eq)]
pub enum CredentialRuntimeError {
    #[error("credential binding is not configured")]
    NotBound,
    #[error("credential was not found")]
    NotFound,
    #[error("credential is archived")]
    Archived,
    #[error("credential project does not match")]
    ProjectMismatch,
    #[error("credential kind does not match binding")]
    KindMismatch,
    #[error("credential field is missing")]
    FieldMissing,
    #[error("credential scheme is unsupported")]
    UnsupportedScheme,
    #[error("credential record is corrupt")]
    CorruptRecord,
    #[error("credential envelope is invalid")]
    EnvelopeInvalid,
}

impl CredentialRuntimeError {
    pub const ALL: [Self; 9] = [
        Self::NotBound,
        Self::NotFound,
        Self::Archived,
        Self::ProjectMismatch,
        Self::KindMismatch,
        Self::FieldMissing,
        Self::UnsupportedScheme,
        Self::CorruptRecord,
        Self::EnvelopeInvalid,
    ];

    pub const fn contract_code(self) -> &'static str {
        match self {
            Self::NotBound => "not_bound",
            Self::NotFound => "not_found",
            Self::Archived => "archived",
            Self::ProjectMismatch => "project_mismatch",
            Self::KindMismatch => "kind_mismatch",
            Self::FieldMissing => "field_missing",
            Self::UnsupportedScheme => "unsupported_scheme",
            Self::CorruptRecord => "corrupt_record",
            Self::EnvelopeInvalid => "envelope_invalid",
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct BoundCredentialState<'a> {
    pub project_id: &'a ProjectId,
    pub archived: bool,
    pub deleted: bool,
}

pub fn require_bound_credential_id(
    credential_id: Option<CredentialId>,
) -> Result<CredentialId, CredentialRuntimeError> {
    credential_id.ok_or(CredentialRuntimeError::NotBound)
}

pub fn require_bound_project(
    project_id: Option<ProjectId>,
    _credential_id: CredentialId,
) -> Result<ProjectId, CredentialRuntimeError> {
    project_id.ok_or(CredentialRuntimeError::ProjectMismatch)
}

pub fn validate_bound_credential(
    project_id: Option<ProjectId>,
    credential_id: CredentialId,
    state: Option<BoundCredentialState<'_>>,
) -> Result<(), CredentialRuntimeError> {
    let project_id = require_bound_project(project_id, credential_id)?;
    let state = state.ok_or(CredentialRuntimeError::NotFound)?;
    if state.deleted {
        return Err(CredentialRuntimeError::NotFound);
    }
    if *state.project_id != project_id {
        return Err(CredentialRuntimeError::ProjectMismatch);
    }
    if state.archived {
        return Err(CredentialRuntimeError::Archived);
    }
    Ok(())
}

pub fn credential_material_object(
    material: &serde_json::Value,
) -> Result<&serde_json::Map<String, serde_json::Value>, CredentialRuntimeError> {
    material
        .as_object()
        .ok_or(CredentialRuntimeError::CorruptRecord)
}

pub fn credential_material_field<'a>(
    material: &'a serde_json::Map<String, serde_json::Value>,
    field: &str,
) -> Result<&'a str, CredentialRuntimeError> {
    let value = material
        .get(field)
        .ok_or(CredentialRuntimeError::FieldMissing)?;
    let value = value
        .as_str()
        .ok_or(CredentialRuntimeError::CorruptRecord)?;
    if value.is_empty() {
        return Err(CredentialRuntimeError::FieldMissing);
    }
    Ok(value)
}
