use std::collections::BTreeMap;
use std::fmt;
use std::ops::Index;

use crate::ids::{CredentialGroupId, CredentialId};

use super::error::CredentialRuntimeError;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ProjectId(String);

impl ProjectId {
    pub fn parse(value: &str) -> Result<Self, CredentialRuntimeError> {
        let value = value.trim();
        if value.is_empty() {
            return Err(CredentialRuntimeError::ProjectMismatch);
        }
        Ok(Self(value.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CredentialKind {
    Model,
    Service,
    Mcp,
}

impl CredentialKind {
    pub fn parse(value: &str) -> Result<Self, CredentialRuntimeError> {
        match value {
            "model" => Ok(Self::Model),
            "service" => Ok(Self::Service),
            "mcp" => Ok(Self::Mcp),
            _ => Err(CredentialRuntimeError::CorruptRecord),
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Model => "model",
            Self::Service => "service",
            Self::Mcp => "mcp",
        }
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct CredentialMaterial {
    values: BTreeMap<String, String>,
}

impl fmt::Debug for CredentialMaterial {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CredentialMaterial")
            .field("fields", &self.values.keys().collect::<Vec<_>>())
            .field("values", &"<redacted>")
            .finish()
    }
}

impl CredentialMaterial {
    pub(crate) fn new(values: BTreeMap<String, String>) -> Self {
        Self { values }
    }

    pub fn require(&self, field: &str) -> Result<&str, CredentialRuntimeError> {
        self.values
            .get(field)
            .map(String::as_str)
            .filter(|value| !value.is_empty())
            .ok_or(CredentialRuntimeError::FieldMissing)
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &str)> {
        self.values
            .iter()
            .map(|(key, value)| (key.as_str(), value.as_str()))
    }
}

impl Index<&str> for CredentialMaterial {
    type Output = String;

    fn index(&self, field: &str) -> &Self::Output {
        &self.values[field]
    }
}

#[derive(Clone)]
pub struct CredentialRecord {
    pub id: CredentialId,
    pub project_id: ProjectId,
    pub kind: CredentialKind,
    pub provider: Option<String>,
    pub protocol: Option<String>,
    pub group_id: Option<CredentialGroupId>,
    pub server_url: Option<String>,
    pub normalized_server_url: Option<String>,
    pub auth_scheme: Option<String>,
    pub material: CredentialMaterial,
}

impl fmt::Debug for CredentialRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CredentialRecord")
            .field("id", &self.id)
            .field("project_id", &self.project_id)
            .field("kind", &self.kind)
            .field("provider", &self.provider)
            .field("protocol", &self.protocol)
            .field("group_id", &self.group_id)
            .field("server_url", &self.server_url)
            .field("normalized_server_url", &self.normalized_server_url)
            .field("auth_scheme", &self.auth_scheme)
            .field("material", &self.material)
            .finish()
    }
}

#[derive(Clone)]
pub struct McpCredentialRecord {
    pub id: CredentialId,
    pub project_id: ProjectId,
    pub group_id: CredentialGroupId,
    pub server_url: String,
    pub normalized_server_url: String,
    pub auth_scheme: String,
    pub material: CredentialMaterial,
}

impl fmt::Debug for McpCredentialRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("McpCredentialRecord")
            .field("id", &self.id)
            .field("project_id", &self.project_id)
            .field("group_id", &self.group_id)
            .field("server_url", &self.server_url)
            .field("normalized_server_url", &self.normalized_server_url)
            .field("auth_scheme", &self.auth_scheme)
            .field("material", &self.material)
            .finish()
    }
}
