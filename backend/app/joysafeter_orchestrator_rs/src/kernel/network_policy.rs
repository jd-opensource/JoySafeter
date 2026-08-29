use std::net::IpAddr;

use anyhow::Context;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

use self::envoy_model::{
    EgressCredentialRoute, EgressPathMapping, EgressPathMatcher, SandboxCredentials,
    SandboxEgressPolicy,
};
use crate::ids::SandboxId;

pub mod application;
pub mod authority;
pub mod envoy_model;
pub mod material;
pub mod ports;
pub mod recovery;
pub mod request;

pub use request::{NetworkPolicyAction, NetworkPolicyRequest};

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct NetworkPolicyGeneration {
    pub policy_hash: String,
    pub policy_version: i64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NetworkPolicyRevision(String);

impl NetworkPolicyRevision {
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Display for NetworkPolicyRevision {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

#[derive(Clone)]
pub struct DesiredNetworkPolicy {
    network_mode: String,
    allowlist_hosts: Vec<String>,
    credentials: SandboxCredentials,
    semantic_routes: Vec<Value>,
}

impl DesiredNetworkPolicy {
    pub fn from_inputs(
        networking: Option<&Value>,
        credentials: &SandboxCredentials,
    ) -> anyhow::Result<Self> {
        let network_mode = networking
            .and_then(|value| value.get("type"))
            .and_then(Value::as_str)
            .unwrap_or("default")
            .trim()
            .to_ascii_lowercase();

        let mut allowlist_hosts = networking
            .and_then(|value| value.get("allowed_hosts"))
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
            .map(canonical_host)
            .collect::<anyhow::Result<Vec<_>>>()?;
        allowlist_hosts.sort();
        allowlist_hosts.dedup();

        let mut semantic_routes = credentials
            .routes
            .iter()
            .map(canonical_route)
            .collect::<anyhow::Result<Vec<_>>>()?;
        semantic_routes.sort_by_key(Value::to_string);

        Ok(Self {
            network_mode,
            allowlist_hosts,
            credentials: credentials.clone(),
            semantic_routes,
        })
    }

    pub fn revision(&self) -> NetworkPolicyRevision {
        NetworkPolicyRevision(sha256_hex(&self.redacted_summary().to_string()))
    }

    pub fn redacted_summary(&self) -> Value {
        json!({
            "network_mode": self.network_mode,
            "allowlist_hosts": self.allowlist_hosts,
            "credential_routes": self.semantic_routes,
        })
    }

    pub fn render_for(&self, sandbox_id: SandboxId) -> SandboxEgressPolicy {
        self.credentials
            .to_policy(&sandbox_id, self.allowlist_hosts.clone())
    }
}

fn canonical_route(route: &EgressCredentialRoute) -> anyhow::Result<Value> {
    let mut vetted_addresses = route
        .vetted_addresses
        .iter()
        .map(|address| {
            address
                .parse::<IpAddr>()
                .with_context(|| format!("invalid vetted egress address {address}"))
                .map(|address| address.to_string())
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    vetted_addresses.sort();
    vetted_addresses.dedup();

    let mut inject_headers = route
        .inject_headers
        .iter()
        .map(|(name, value)| {
            json!({
                "name": name.trim().to_ascii_lowercase(),
                "value_sha256": sha256_hex(value),
            })
        })
        .collect::<Vec<_>>();
    inject_headers.sort_by_key(Value::to_string);

    let mut remove_headers = route
        .remove_headers
        .iter()
        .map(|name| name.trim().to_ascii_lowercase())
        .collect::<Vec<_>>();
    remove_headers.sort();
    remove_headers.dedup();

    Ok(json!({
        "kind": format!("{:?}", route.kind).to_ascii_lowercase(),
        "exposure": format!("{:?}", route.exposure).to_ascii_lowercase(),
        "match_host": canonical_host(&route.match_host)?,
        "path_mapping": canonical_path_mapping(&route.path_mapping),
        "retry_mode": format!("{:?}", route.retry_mode).to_ascii_lowercase(),
        "upstream_host": canonical_host(&route.upstream_host)?,
        "upstream_port": route.upstream_port,
        "upstream_tls": route.upstream_tls,
        "vetted_addresses": vetted_addresses,
        "inject_headers": inject_headers,
        "remove_headers": remove_headers,
    }))
}

fn canonical_path_mapping(mapping: &EgressPathMapping) -> Value {
    match mapping {
        EgressPathMapping::Passthrough { matcher } => match matcher {
            EgressPathMatcher::Any => json!({"kind": "passthrough_any"}),
            EgressPathMatcher::Exact(path) => {
                json!({"kind": "passthrough_exact", "path": canonical_path(path)})
            }
            EgressPathMatcher::Prefix(path) => {
                json!({"kind": "passthrough_prefix", "path": canonical_path(path)})
            }
        },
        EgressPathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        } => json!({
            "kind": "rewrite_exact",
            "exposed_path": canonical_path(exposed_path),
            "upstream_path": canonical_path(upstream_path),
        }),
        EgressPathMapping::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        } => json!({
            "kind": "rewrite_prefix",
            "exposed_prefix": canonical_path(exposed_prefix),
            "upstream_prefix": canonical_path(upstream_prefix),
        }),
    }
}

fn canonical_host(host: &str) -> anyhow::Result<String> {
    let host = host.trim().trim_end_matches('.').to_ascii_lowercase();
    if host.is_empty() {
        anyhow::bail!("network policy host is empty");
    }
    Ok(host)
}

fn canonical_path(path: &str) -> String {
    if path.is_empty() {
        "/".to_string()
    } else if path.starts_with('/') {
        path.to_string()
    } else {
        format!("/{path}")
    }
}

fn sha256_hex(value: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(value.as_bytes());
    hex::encode(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::envoy_model::{EgressExposure, EgressKind, EgressRetryMode};
    use super::*;
    use uuid::Uuid;

    fn credentials() -> SandboxCredentials {
        SandboxCredentials {
            routes: vec![EgressCredentialRoute {
                id: "database-row-id".to_string(),
                kind: EgressKind::Mcp,
                exposure: EgressExposure::Placeholder,
                match_host: "MCP-EGRESS.INTERNAL.".to_string(),
                path_mapping: EgressPathMapping::RewritePrefix {
                    exposed_prefix: "r/server/".to_string(),
                    upstream_prefix: "mcp".to_string(),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: "EXAMPLE.COM.".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: String::new(),
                vetted_addresses: vec!["2001:db8::1".to_string(), "192.0.2.10".to_string()],
                inject_headers: vec![("Authorization".to_string(), "secret".to_string())],
                remove_headers: vec!["AUTHORIZATION".to_string()],
            }],
            proxy_auth_token: Some("proxy-secret".to_string()),
        }
    }

    #[test]
    fn semantic_network_policy_ignores_rendered_resource_names_and_order() {
        let networking = json!({
            "type": "LIMITED",
            "allowed_hosts": ["Example.COM.", "mcp-egress.internal"]
        });
        let first = DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials()).unwrap();
        let mut reordered = credentials();
        reordered.routes[0].id = "different-row-id".to_string();
        reordered.routes[0].cluster_name = "different-rendered-name".to_string();
        reordered.routes[0].vetted_addresses.reverse();
        reordered.routes[0].inject_headers[0].0 = "authorization".to_string();
        let reordered_networking = json!({
            "allowed_hosts": ["MCP-EGRESS.INTERNAL", "example.com"],
            "type": "limited"
        });
        let second =
            DesiredNetworkPolicy::from_inputs(Some(&reordered_networking), &reordered).unwrap();

        assert_eq!(first.revision(), second.revision());
    }

    #[test]
    fn semantic_network_policy_changes_for_enforcement_inputs() {
        let networking = json!({"type": "limited", "allowed_hosts": ["example.com"]});
        let baseline = DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials())
            .unwrap()
            .revision();
        let mutations: Vec<Box<dyn Fn(&mut SandboxCredentials)>> = vec![
            Box::new(|value| value.routes[0].upstream_host = "other.example".to_string()),
            Box::new(|value| {
                value.routes[0].path_mapping = EgressPathMapping::RewritePrefix {
                    exposed_prefix: "/r/server/".to_string(),
                    upstream_prefix: "/other".to_string(),
                }
            }),
            Box::new(|value| value.routes[0].retry_mode = EgressRetryMode::Disabled),
            Box::new(|value| value.routes[0].upstream_tls = false),
            Box::new(|value| {
                value.routes[0]
                    .vetted_addresses
                    .push("192.0.2.11".to_string())
            }),
            Box::new(|value| value.routes[0].inject_headers[0].1 = "other-secret".to_string()),
            Box::new(|value| value.routes[0].remove_headers.clear()),
        ];

        for mutate in mutations {
            let mut changed = credentials();
            mutate(&mut changed);
            assert_ne!(
                baseline,
                DesiredNetworkPolicy::from_inputs(Some(&networking), &changed)
                    .unwrap()
                    .revision()
            );
        }
    }

    #[test]
    fn rendered_policy_does_not_change_semantic_revision() {
        let networking = json!({"type": "limited", "allowed_hosts": ["example.com"]});
        let desired = DesiredNetworkPolicy::from_inputs(Some(&networking), &credentials()).unwrap();
        let revision = desired.revision();

        let first = desired.render_for(SandboxId::from_uuid(Uuid::from_u128(1)));
        let second = desired.render_for(SandboxId::from_uuid(Uuid::from_u128(2)));

        assert_ne!(
            first.credential_routes[0].cluster_name,
            second.credential_routes[0].cluster_name
        );
        assert_eq!(revision, desired.revision());
    }
}
