use std::collections::HashMap;

use anyhow::Context;

use crate::ids::{CredentialId, ProjectId};
use crate::kernel::agent_identity_provider::IdentityEgressRequestTarget;
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::error::CredentialRuntimeError;
use crate::kernel::credentials::reference::decode_environment;
use crate::kernel::network_policy::envoy_model::{
    EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping, EgressPathMatcher,
    EgressRetryMode, UpstreamTarget,
};

use super::EnvironmentRow;

/// Build external-service egress routes from `environment.config.egress_services`.
///
/// For each service, emits a placeholder route (on `external-egress.internal`)
/// and a transparent route (on the real host) so skills can use either URL
/// pattern. The secret is decrypted and headers are built according to the
/// `inject` config (bearer / api_key / cookie).
pub(crate) async fn build_external_egress(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    environment: Option<&EnvironmentRow>,
    project_id: Option<ProjectId>,
) -> anyhow::Result<(Vec<EgressCredentialRoute>, Vec<IdentityEgressRequestTarget>)> {
    let Some(environment) = environment else {
        return Ok((vec![], vec![]));
    };
    let decoded = decode_environment(&environment.config)?;

    let mut routes = Vec::new();
    for reference in decoded.http_egress {
        let name = reference
            .name
            .as_deref()
            .ok_or(CredentialRuntimeError::FieldMissing)?;
        let name = sanitize_external_service_name(name);
        if name.is_empty() {
            return Err(CredentialRuntimeError::CorruptRecord.into());
        }

        let upstream = UpstreamTarget::from_url(&reference.endpoint)
            .map_err(|_| CredentialRuntimeError::CorruptRecord)?;
        let host = upstream.host;
        let tls = upstream.tls;
        let port = upstream.port;
        let upstream_prefix = normalize_external_upstream_prefix(&upstream.prefix);

        let credential_id = reference.credential_id;
        let credential_field = reference.credential_field.as_str();
        let credential_value = load_service_egress_field(
            credential_access,
            access_context,
            credential_id,
            project_id,
            credential_field,
        )
        .await
        .with_context(|| {
            format!("failed to load external egress service {name:?} credential {credential_id}")
        })?;
        let secret = HashMap::from([(credential_field.to_string(), credential_value)]);
        let headers = build_external_inject_headers(
            &secret,
            &reference.inject_kind,
            credential_field,
            reference.header.as_deref(),
        )?;

        let remove_headers = vec![
            "authorization".to_string(),
            "cookie".to_string(),
            "x-api-key".to_string(),
            "api-key".to_string(),
            "x-goog-api-key".to_string(),
        ];

        // Transparent route(s): sandbox calls the real host over plaintext http.
        // Envoy matches the real host vhost, injects the credential, and
        // TLS-originates to the real upstream when needed.
        let allowed_paths = reference.allowed_paths;

        if allowed_paths.is_empty() {
            routes.push(EgressCredentialRoute {
                id: format!("external-direct:{name}"),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: host.clone(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Prefix(upstream_prefix.clone()),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: host.clone(),
                upstream_port: port,
                upstream_tls: tls,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: headers.clone(),
                remove_headers: remove_headers.clone(),
            });
        } else {
            for (idx, entry) in allowed_paths.iter().enumerate() {
                let is_prefix = entry.ends_with('/');
                let full_path = join_service_path(&upstream_prefix, entry);
                routes.push(EgressCredentialRoute {
                    id: format!("external-direct:{name}:{idx}"),
                    kind: EgressKind::External,
                    exposure: EgressExposure::Transparent,
                    match_host: host.clone(),
                    path_mapping: EgressPathMapping::Passthrough {
                        matcher: if is_prefix {
                            EgressPathMatcher::Prefix(full_path.clone())
                        } else {
                            EgressPathMatcher::Exact(full_path.clone())
                        },
                    },
                    retry_mode: EgressRetryMode::SafeIdempotent,
                    upstream_host: host.clone(),
                    upstream_port: port,
                    upstream_tls: tls,
                    cluster_name: String::new(),
                    vetted_addresses: vec![],
                    inject_headers: headers.clone(),
                    remove_headers: remove_headers.clone(),
                });
            }
        }
    }
    let mut identity_targets = Vec::new();
    let services = environment
        .config
        .get("egress_services")
        .and_then(serde_json::Value::as_array)
        .cloned()
        .unwrap_or_default();
    for service in services {
        let service = service
            .as_object()
            .ok_or(CredentialRuntimeError::CorruptRecord)?;
        let auth_source = service
            .get("auth_source")
            .and_then(serde_json::Value::as_str)
            .unwrap_or("service_credential");
        if auth_source != "agent_identity" {
            continue;
        }
        if service
            .get("credential_ref")
            .is_some_and(|value| !value.is_null())
            || service.get("inject").is_some_and(|value| !value.is_null())
        {
            return Err(CredentialRuntimeError::CorruptRecord.into());
        }
        let name = sanitize_external_service_name(
            service
                .get("name")
                .and_then(serde_json::Value::as_str)
                .ok_or(CredentialRuntimeError::FieldMissing)?,
        );
        if name.is_empty() {
            return Err(CredentialRuntimeError::CorruptRecord.into());
        }
        let endpoint = service
            .get("base_url")
            .and_then(serde_json::Value::as_str)
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or(CredentialRuntimeError::FieldMissing)?
            .to_string();
        let upstream = UpstreamTarget::from_url(&endpoint)
            .map_err(|_| CredentialRuntimeError::CorruptRecord)?;
        let upstream_prefix = normalize_external_upstream_prefix(&upstream.prefix);
        let default_allowed_paths = vec![serde_json::Value::String("/".to_string())];
        let allowed_paths = match service.get("allowed_paths") {
            None | Some(serde_json::Value::Null) => &default_allowed_paths,
            Some(serde_json::Value::Array(paths)) if paths.is_empty() => &default_allowed_paths,
            Some(serde_json::Value::Array(paths)) => paths,
            Some(_) => return Err(CredentialRuntimeError::CorruptRecord.into()),
        };
        for (index, entry) in allowed_paths.iter().enumerate() {
            let entry = entry
                .as_str()
                .filter(|path| path.starts_with('/') && !path.contains(['?', '#']))
                .ok_or(CredentialRuntimeError::CorruptRecord)?;
            let full_path = join_service_path(&upstream_prefix, entry);
            let route_id = format!("external-identity:{name}:{index}");
            routes.push(EgressCredentialRoute {
                id: route_id.clone(),
                kind: EgressKind::External,
                exposure: EgressExposure::Transparent,
                match_host: upstream.host.clone(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: if entry.ends_with('/') {
                        EgressPathMatcher::Prefix(full_path)
                    } else {
                        EgressPathMatcher::Exact(full_path)
                    },
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: upstream.host.clone(),
                upstream_port: upstream.port,
                upstream_tls: upstream.tls,
                cluster_name: String::new(),
                vetted_addresses: vec![],
                inject_headers: vec![],
                remove_headers: vec![
                    "authorization".to_string(),
                    "cookie".to_string(),
                    "x-security-agenttoken".to_string(),
                ],
            });
            identity_targets.push(IdentityEgressRequestTarget {
                route_id,
                endpoint: endpoint.clone(),
                host: upstream.host.clone(),
                port: upstream.port,
                tls: upstream.tls,
            });
        }
    }
    Ok((routes, identity_targets))
}

async fn load_service_egress_field(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    credential_id: CredentialId,
    project_id: Option<ProjectId>,
    field: &str,
) -> anyhow::Result<String> {
    let project_id = project_id.ok_or(CredentialRuntimeError::ProjectMismatch)?;
    credential_access
        .resolve_http_egress_field(&project_id, credential_id, field, access_context)
        .await
}

fn sanitize_external_service_name(name: &str) -> String {
    name.trim()
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || c == '-' || c == '_' {
                c.to_ascii_lowercase()
            } else {
                '-'
            }
        })
        .collect::<String>()
        .trim_matches('-')
        .to_string()
}

fn normalize_external_upstream_prefix(path: &str) -> String {
    let mut prefix = if path.is_empty() {
        "/".to_string()
    } else if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    };
    if prefix != "/" && !prefix.ends_with('/') {
        prefix.push('/');
    }
    prefix
}

/// Join a service base prefix with an allowlist entry into a full host path.
fn join_service_path(base_prefix: &str, entry: &str) -> String {
    if entry.starts_with('/') {
        return entry.to_string();
    }
    let base = base_prefix.strip_suffix('/').unwrap_or(base_prefix);
    format!("{base}/{entry}")
}

fn build_external_inject_headers(
    secret: &HashMap<String, String>,
    inject_kind: &str,
    credential_field: &str,
    header: Option<&str>,
) -> Result<Vec<(String, String)>, CredentialRuntimeError> {
    match inject_kind {
        "bearer" => {
            let token = secret
                .get(credential_field)
                .filter(|value| !value.is_empty())
                .ok_or(CredentialRuntimeError::FieldMissing)?;
            let header = header.unwrap_or("authorization");
            Ok(vec![(header.to_string(), format!("Bearer {token}"))])
        }
        "api_key" | "raw_header" => {
            let value = secret
                .get(credential_field)
                .filter(|value| !value.is_empty())
                .ok_or(CredentialRuntimeError::FieldMissing)?;
            let header = header.unwrap_or("x-api-key");
            Ok(vec![(header.to_string(), value.clone())])
        }
        "cookie" => {
            let cookie_header = secret
                .get(credential_field)
                .filter(|value| !value.is_empty())
                .ok_or(CredentialRuntimeError::FieldMissing)?
                .clone();
            Ok(vec![("cookie".to_string(), cookie_header)])
        }
        _ => Err(CredentialRuntimeError::UnsupportedScheme),
    }
}
