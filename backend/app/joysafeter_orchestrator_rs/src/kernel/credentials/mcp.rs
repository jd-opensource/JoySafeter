use std::collections::HashSet;
use std::fmt;

use crate::ids::CredentialId;

use super::error::CredentialRuntimeError;
use super::record::{McpCredentialMetadataRecord, McpCredentialRecord};

const RESERVED_HEADER_NAMES: &[&str] = &[
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
];

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
pub struct McpHeaderInjection {
    pub header_name: String,
    pub header_value: String,
    pub remove_headers: Vec<String>,
}

impl fmt::Debug for McpHeaderInjection {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("McpHeaderInjection")
            .field("header_name", &self.header_name)
            .field("header_value", &"<redacted>")
            .field("remove_headers", &self.remove_headers)
            .finish()
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct ResolvedMcpCredential {
    pub id: CredentialId,
    pub server_url: String,
    pub normalized_server_url: String,
    pub auth_scheme: String,
    pub injection: McpHeaderInjection,
}

impl fmt::Debug for ResolvedMcpCredential {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedMcpCredential")
            .field("id", &self.id)
            .field("server_url", &self.server_url)
            .field("normalized_server_url", &self.normalized_server_url)
            .field("auth_scheme", &self.auth_scheme)
            .field("injection", &self.injection)
            .finish()
    }
}

fn has_control_characters(value: &str) -> bool {
    value.chars().any(|character| character.is_control())
}

fn is_valid_header_name(value: &str) -> bool {
    !value.is_empty()
        && value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || matches!(
                    byte,
                    b'!' | b'#'
                        | b'$'
                        | b'%'
                        | b'&'
                        | b'\''
                        | b'*'
                        | b'+'
                        | b'-'
                        | b'.'
                        | b'^'
                        | b'_'
                        | b'`'
                        | b'|'
                        | b'~'
                )
        })
}

fn normalize_header_name(value: &str) -> Result<String, CredentialRuntimeError> {
    let normalized = value.trim().to_ascii_lowercase();
    if !is_valid_header_name(&normalized)
        || RESERVED_HEADER_NAMES.contains(&normalized.as_str())
        || normalized.starts_with("x-envoy-")
    {
        return Err(CredentialRuntimeError::CorruptRecord);
    }
    Ok(normalized)
}

fn resolve_injection(
    auth_scheme: &str,
    material: &super::record::CredentialMaterial,
) -> Result<McpHeaderInjection, CredentialRuntimeError> {
    let token = material.require("token_value")?.trim();
    if token.is_empty() {
        return Err(CredentialRuntimeError::FieldMissing);
    }
    if has_control_characters(token) {
        return Err(CredentialRuntimeError::CorruptRecord);
    }

    let (header_name, header_value) = match auth_scheme {
        "static_bearer" => ("authorization".to_string(), format!("Bearer {token}")),
        "header_api_key" => {
            let header_name = material
                .iter()
                .find_map(|(key, value)| (key == "header_name").then_some(value))
                .unwrap_or("X-Api-Key");
            (normalize_header_name(header_name)?, token.to_string())
        }
        "custom_header" => {
            let header_name = normalize_header_name(material.require("header_name")?)?;
            let value_prefix = material
                .iter()
                .find_map(|(key, value)| (key == "value_prefix").then_some(value))
                .unwrap_or("");
            if has_control_characters(value_prefix) {
                return Err(CredentialRuntimeError::CorruptRecord);
            }
            (header_name, format!("{value_prefix}{token}"))
        }
        _ => return Err(CredentialRuntimeError::UnsupportedScheme),
    };

    let mut remove_headers = vec!["authorization".to_string(), "x-api-key".to_string()];
    if !remove_headers.contains(&header_name) {
        remove_headers.push(header_name.clone());
    }
    Ok(McpHeaderInjection {
        header_name,
        header_value,
        remove_headers,
    })
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
        resolved.push(ResolvedMcpCredential {
            id: member.id,
            server_url: member.server_url.clone(),
            normalized_server_url: member.normalized_server_url.clone(),
            auth_scheme: member.auth_scheme.clone(),
            injection: resolve_injection(&member.auth_scheme, &member.material)?,
        });
    }
    Ok(resolved)
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use uuid::Uuid;

    use crate::ids::{CredentialGroupId, CredentialId};

    use super::{resolve_mcp_members, CredentialRuntimeError};
    use crate::ids::ProjectId;
    use crate::kernel::credentials::record::{CredentialMaterial, McpCredentialRecord};

    fn record(auth_scheme: &str, fields: &[(&str, &str)]) -> McpCredentialRecord {
        McpCredentialRecord {
            id: CredentialId::from_uuid(Uuid::nil()),
            project_id: ProjectId::from_uuid(uuid::Uuid::from_u128(1)),
            group_id: CredentialGroupId::from_uuid(Uuid::nil()),
            server_url: "https://example.com/mcp".to_string(),
            normalized_server_url: "https://example.com/mcp".to_string(),
            auth_scheme: auth_scheme.to_string(),
            material: CredentialMaterial::new(
                fields
                    .iter()
                    .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
                    .collect::<BTreeMap<_, _>>(),
            ),
        }
    }

    #[test]
    fn static_bearer_builds_authorization_injection() {
        let resolved =
            resolve_mcp_members(&[record("static_bearer", &[("token_value", "secret")])]).unwrap();

        assert_eq!(resolved[0].injection.header_name, "authorization");
        assert_eq!(resolved[0].injection.header_value, "Bearer secret");
        assert_eq!(
            resolved[0].injection.remove_headers,
            vec!["authorization", "x-api-key"]
        );
    }

    #[test]
    fn header_api_key_defaults_and_honors_header_name() {
        let defaulted =
            resolve_mcp_members(&[record("header_api_key", &[("token_value", "secret")])]).unwrap();
        assert_eq!(defaulted[0].injection.header_name, "x-api-key");
        assert_eq!(defaulted[0].injection.header_value, "secret");

        let custom = resolve_mcp_members(&[record(
            "header_api_key",
            &[("token_value", "secret"), ("header_name", "X-Corp-Key")],
        )])
        .unwrap();
        assert_eq!(custom[0].injection.header_name, "x-corp-key");
    }

    #[test]
    fn custom_header_applies_prefix() {
        let resolved = resolve_mcp_members(&[record(
            "custom_header",
            &[
                ("token_value", "secret"),
                ("header_name", "X-Service-Authorization"),
                ("value_prefix", "Token "),
            ],
        )])
        .unwrap();

        assert_eq!(resolved[0].injection.header_name, "x-service-authorization");
        assert_eq!(resolved[0].injection.header_value, "Token secret");
        assert_eq!(
            resolved[0].injection.remove_headers,
            vec!["authorization", "x-api-key", "x-service-authorization"]
        );
    }

    #[test]
    fn unsafe_headers_and_values_fail_closed() {
        for fields in [
            vec![("token_value", "secret"), ("header_name", "Host")],
            vec![("token_value", "secret"), ("header_name", "X-Envoy-Test")],
            vec![
                ("token_value", "secret\r\nX-Evil: yes"),
                ("header_name", "X-Token"),
            ],
        ] {
            assert_eq!(
                resolve_mcp_members(&[record("custom_header", &fields)]),
                Err(CredentialRuntimeError::CorruptRecord)
            );
        }
    }

    #[test]
    fn unknown_scheme_remains_unsupported() {
        assert_eq!(
            resolve_mcp_members(&[record("basic", &[("token_value", "secret")])]),
            Err(CredentialRuntimeError::UnsupportedScheme)
        );
    }
}
