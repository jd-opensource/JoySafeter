use std::collections::HashSet;
use std::fmt;

use crate::ids::CredentialId;

use super::error::CredentialRuntimeError;
use super::record::{McpCredentialMetadataRecord, McpCredentialRecord};

pub fn resolve_mcp_member_urls(
    members: &[McpCredentialMetadataRecord],
) -> Result<HashSet<String>, CredentialRuntimeError> {
    let mut normalized_urls = HashSet::new();
    for member in members {
        if !normalized_urls.insert(member.normalized_server_url.clone()) {
            return Err(CredentialRuntimeError::CorruptRecord);
        }
    }
    Ok(normalized_urls)
}

#[derive(Clone, PartialEq, Eq)]
pub struct ResolvedMcpCredential {
    pub id: CredentialId,
    pub server_url: String,
    pub normalized_server_url: String,
    pub auth_scheme: String,
    pub token: String,
}

impl fmt::Debug for ResolvedMcpCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedMcpCredential")
            .field("id", &self.id)
            .field("server_url", &self.server_url)
            .field("normalized_server_url", &self.normalized_server_url)
            .field("auth_scheme", &self.auth_scheme)
            .field("token", &"<redacted>")
            .finish()
    }
}

pub fn resolve_mcp_members(
    members: &[McpCredentialRecord],
) -> Result<Vec<ResolvedMcpCredential>, CredentialRuntimeError> {
    let mut seen_urls = HashSet::new();
    let mut resolved = Vec::with_capacity(members.len());
    for member in members {
        if !seen_urls.insert(member.normalized_server_url.as_str()) {
            return Err(CredentialRuntimeError::CorruptRecord);
        }
        if member.auth_scheme != "static_bearer" {
            return Err(CredentialRuntimeError::UnsupportedScheme);
        }
        resolved.push(ResolvedMcpCredential {
            id: member.id,
            server_url: member.server_url.clone(),
            normalized_server_url: member.normalized_server_url.clone(),
            auth_scheme: member.auth_scheme.clone(),
            token: member.material.require("token_value")?.to_string(),
        });
    }
    Ok(resolved)
}
