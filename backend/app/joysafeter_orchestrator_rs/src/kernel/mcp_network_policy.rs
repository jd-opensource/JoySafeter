use std::collections::BTreeSet;
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr};

use async_trait::async_trait;
use thiserror::Error;

const BLOCKED_HOSTNAMES: &[&str] = &["metadata.google.internal", "metadata.goog"];
const METADATA_IPV4: &[Ipv4Addr] = &[
    Ipv4Addr::new(169, 254, 169, 254),
    Ipv4Addr::new(169, 254, 170, 2),
    Ipv4Addr::new(100, 100, 100, 200),
];
const METADATA_IPV6: Ipv6Addr = Ipv6Addr::new(0xfd00, 0x0ec2, 0, 0, 0, 0, 0, 0x0254);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct McpNetworkPolicy {
    pub allow_private: bool,
}

impl Default for McpNetworkPolicy {
    fn default() -> Self {
        Self {
            allow_private: true,
        }
    }
}

impl McpNetworkPolicy {
    pub fn from_env() -> Self {
        let block_private = std::env::var("JOYSAFETER_SSRF_BLOCK_PRIVATE")
            .ok()
            .is_some_and(|value| matches!(value.to_ascii_lowercase().as_str(), "1" | "true"));
        Self {
            allow_private: !block_private,
        }
    }
}

#[derive(Debug, Clone, Error, PartialEq, Eq)]
pub enum McpNetworkPolicyError {
    #[error("blocked MCP hostname: {host}")]
    BlockedHostname { host: String },
    #[error("MCP hostname resolution failed: {host}")]
    ResolutionFailed { host: String },
    #[error("MCP hostname returned no addresses: {host}")]
    NoAddresses { host: String },
    #[error("MCP hostname {host} resolved to prohibited address {address}")]
    ProhibitedAddress { host: String, address: IpAddr },
}

#[async_trait]
pub trait McpAddressResolver: Send + Sync {
    async fn resolve(&self, host: &str, port: u16) -> Result<Vec<IpAddr>, McpNetworkPolicyError>;
}

pub struct SystemMcpAddressResolver;

#[async_trait]
impl McpAddressResolver for SystemMcpAddressResolver {
    async fn resolve(&self, host: &str, port: u16) -> Result<Vec<IpAddr>, McpNetworkPolicyError> {
        if let Ok(address) = host.parse::<IpAddr>() {
            return Ok(vec![address]);
        }
        tokio::net::lookup_host((host, port))
            .await
            .map(|addresses| addresses.map(|address| address.ip()).collect())
            .map_err(|_| McpNetworkPolicyError::ResolutionFailed {
                host: host.to_string(),
            })
    }
}

fn is_blocked_hostname(host: &str) -> bool {
    BLOCKED_HOSTNAMES
        .iter()
        .any(|blocked| host.eq_ignore_ascii_case(blocked))
}

pub fn validate_resolved_addresses(
    host: &str,
    addresses: impl IntoIterator<Item = IpAddr>,
    policy: &McpNetworkPolicy,
) -> Result<Vec<IpAddr>, McpNetworkPolicyError> {
    if is_blocked_hostname(host) {
        return Err(McpNetworkPolicyError::BlockedHostname {
            host: host.to_string(),
        });
    }

    let mut vetted = BTreeSet::new();
    for address in addresses {
        if is_prohibited(address, policy) {
            return Err(McpNetworkPolicyError::ProhibitedAddress {
                host: host.to_string(),
                address,
            });
        }
        vetted.insert(address);
    }
    if vetted.is_empty() {
        return Err(McpNetworkPolicyError::NoAddresses {
            host: host.to_string(),
        });
    }
    Ok(vetted.into_iter().collect())
}

pub async fn resolve_vetted_addresses(
    host: &str,
    port: u16,
    policy: &McpNetworkPolicy,
) -> Result<Vec<IpAddr>, McpNetworkPolicyError> {
    resolve_vetted_addresses_with(&SystemMcpAddressResolver, host, port, policy).await
}

pub async fn resolve_vetted_addresses_with(
    resolver: &dyn McpAddressResolver,
    host: &str,
    port: u16,
    policy: &McpNetworkPolicy,
) -> Result<Vec<IpAddr>, McpNetworkPolicyError> {
    // Fail fast on blocked hostnames before issuing a DNS lookup for them.
    if is_blocked_hostname(host) {
        return Err(McpNetworkPolicyError::BlockedHostname {
            host: host.to_string(),
        });
    }
    let addresses = resolver.resolve(host, port).await?;
    validate_resolved_addresses(host, addresses, policy)
}

fn is_prohibited(address: IpAddr, policy: &McpNetworkPolicy) -> bool {
    match address {
        IpAddr::V4(address) => {
            METADATA_IPV4.contains(&address)
                || address.is_unspecified()
                || address.is_link_local()
                || address.is_multicast()
                || address.is_broadcast()
                || (!policy.allow_private && (address.is_private() || address.is_loopback()))
        }
        IpAddr::V6(address) => {
            address == METADATA_IPV6
                || address.is_unspecified()
                || address.is_unicast_link_local()
                || address.is_multicast()
                || (!policy.allow_private && (address.is_unique_local() || address.is_loopback()))
        }
    }
}

#[cfg(test)]
mod tests {
    use std::net::IpAddr;
    use std::path::PathBuf;

    use super::{validate_resolved_addresses, McpNetworkPolicy};

    #[derive(serde::Deserialize)]
    struct Vector {
        address: String,
        default_allowed: bool,
    }

    #[test]
    fn address_policy_matches_shared_vectors() {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../tests/fixtures/mcp_network_address_vectors.json");
        let vectors: Vec<Vector> =
            serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
        let policy = McpNetworkPolicy::default();

        for vector in vectors {
            let address: IpAddr = vector.address.parse().unwrap();
            assert_eq!(
                validate_resolved_addresses("mcp.example", [address], &policy).is_ok(),
                vector.default_allowed,
                "unexpected classification for {}",
                vector.address
            );
        }
    }

    #[test]
    fn one_prohibited_dns_answer_rejects_the_whole_endpoint() {
        let result = validate_resolved_addresses(
            "mixed.example",
            [
                "203.0.113.10".parse().unwrap(),
                "169.254.169.254".parse().unwrap(),
            ],
            &McpNetworkPolicy::default(),
        );

        assert!(result.is_err());
    }

    #[test]
    fn deployment_policy_can_block_private_and_loopback_addresses() {
        let policy = McpNetworkPolicy {
            allow_private: false,
        };

        for address in ["127.0.0.1", "10.0.0.1", "::1", "fd00::1"] {
            assert!(validate_resolved_addresses(
                "internal.example",
                [address.parse().unwrap()],
                &policy,
            )
            .is_err());
        }
    }

    #[test]
    fn empty_dns_answer_fails_closed() {
        assert!(validate_resolved_addresses(
            "missing.example",
            std::iter::empty(),
            &McpNetworkPolicy::default(),
        )
        .is_err());
    }

    #[test]
    fn metadata_hostnames_are_rejected_without_dns() {
        assert!(validate_resolved_addresses(
            "metadata.google.internal",
            ["203.0.113.10".parse().unwrap()],
            &McpNetworkPolicy::default(),
        )
        .is_err());
    }
}
