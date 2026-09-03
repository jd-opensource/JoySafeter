use std::env;
use std::net::{IpAddr, SocketAddr};
use std::time::Duration;

use anyhow::Context;

use crate::adapters::management_api::ManagementAuthenticator;
use crate::xds::auth::XdsAuthKeyring;
use crate::xds::control_plane::NodeVisibility;

const DEFAULT_XDS_PORT: u16 = 9092;
const DEFAULT_HTTP_PORT: u16 = 9093;
const DEFAULT_MANAGEMENT_GRPC_PORT: u16 = 9094;
const DEFAULT_DELIVERY_TIMEOUT_SECS: u64 = 20;
const DEFAULT_SHUTDOWN_GRACE_SECS: u64 = 10;
const DEFAULT_REPLICATION_ACK_TIMEOUT_MS: u64 = 1_000;
const DEFAULT_HOT_STANDBY_MIN_ACKS: u32 = 1;
const MIN_TOKEN_BYTES: usize = 32;
const MAX_TOKEN_BYTES: usize = 512;

#[derive(Clone)]
pub struct SecretToken(String);

impl SecretToken {
    fn parse(name: &str, value: String) -> anyhow::Result<Self> {
        let value = value.trim().to_string();
        if !(MIN_TOKEN_BYTES..=MAX_TOKEN_BYTES).contains(&value.len())
            || !value.is_ascii()
            || value.bytes().any(|byte| byte.is_ascii_whitespace())
        {
            anyhow::bail!("{name} must contain 32-512 non-whitespace ASCII bytes");
        }
        Ok(Self(value))
    }

    pub fn expose(&self) -> &str {
        &self.0
    }
}

impl std::fmt::Debug for SecretToken {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str("SecretToken(<redacted>)")
    }
}

#[derive(Clone, Debug)]
pub struct GatewayConfig {
    pub instance_id: String,
    pub xds_addr: SocketAddr,
    pub http_addr: SocketAddr,
    pub management_grpc_addr: SocketAddr,
    pub xds_auth_keyring: XdsAuthKeyring,
    pub management_authenticator: ManagementAuthenticator,
    /// Raw management token, retained so the gRPC management server can build its
    /// own authenticator (the HTTP authenticator only keeps the digest).
    pub management_token: SecretToken,
    pub leader_election_enabled: bool,
    pub k8s_namespace: String,
    pub pod_name: Option<String>,
    pub leader_lease_name: String,
    pub leader_identity: String,
    pub leader_lease_duration: Duration,
    pub leader_renew_interval: Duration,
    pub replication_url: Option<url::Url>,
    pub replication_token: Option<SecretToken>,
    pub hot_standby_min_acks: usize,
    pub replication_ack_timeout: Duration,
    pub node_visibility: NodeVisibility,
    pub delivery_timeout: Duration,
    pub shutdown_grace: Duration,
    /// When set, the gateway subscribes to the orchestrator's policy stream at
    /// this gRPC endpoint instead of (or in addition to) the HTTP management API.
    pub policy_stream_endpoint: Option<String>,
}

impl GatewayConfig {
    pub fn from_env() -> anyhow::Result<Self> {
        let instance_id = env::var("JOYSAFETER_AGENT_GATEWAY_INSTANCE_ID")
            .unwrap_or_else(|_| "agent-gateway-standalone".to_string());
        let xds_host =
            env::var("JOYSAFETER_AGENT_GATEWAY_XDS_HOST").unwrap_or_else(|_| "0.0.0.0".to_string());
        let xds_port = env_u16("JOYSAFETER_AGENT_GATEWAY_XDS_PORT", DEFAULT_XDS_PORT)?;
        let http_host = env::var("JOYSAFETER_AGENT_GATEWAY_HTTP_HOST")
            .unwrap_or_else(|_| "0.0.0.0".to_string());
        let http_port = env_u16("JOYSAFETER_AGENT_GATEWAY_HTTP_PORT", DEFAULT_HTTP_PORT)?;
        let management_grpc_port = env_u16(
            "JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_GRPC_PORT",
            DEFAULT_MANAGEMENT_GRPC_PORT,
        )?;
        let keyring = env::var("JOYSAFETER_XDS_AUTH_KEYRING")
            .context("JOYSAFETER_XDS_AUTH_KEYRING is required")?;
        let write_key_id = env::var("JOYSAFETER_XDS_AUTH_WRITE_KEY_ID")
            .context("JOYSAFETER_XDS_AUTH_WRITE_KEY_ID is required")?;
        let management_token = env::var("JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN")
            .context("JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN is required")?;
        let leader_election_enabled =
            env_bool("JOYSAFETER_AGENT_GATEWAY_LEADER_ELECTION_ENABLED", false)?;
        let k8s_namespace = env::var("POD_NAMESPACE").unwrap_or_else(|_| "default".to_string());
        let pod_name = env::var("POD_NAME")
            .ok()
            .filter(|value| !value.trim().is_empty());
        let leader_identity = env::var("JOYSAFETER_AGENT_GATEWAY_LEADER_IDENTITY")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .or_else(|| pod_name.clone())
            .unwrap_or_else(|| instance_id.clone());
        let leader_lease_name = env::var("JOYSAFETER_AGENT_GATEWAY_LEADER_LEASE_NAME")
            .unwrap_or_else(|_| "joysafeter-agent-gateway".to_string());
        let leader_lease_duration = Duration::from_secs(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_LEADER_LEASE_DURATION_SECS",
            15,
        )?);
        let leader_renew_interval = Duration::from_secs(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_LEADER_RENEW_INTERVAL_SECS",
            5,
        )?);
        let replication_url = env::var("JOYSAFETER_AGENT_GATEWAY_REPLICATION_URL")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .map(|value| {
                url::Url::parse(&value)
                    .context("JOYSAFETER_AGENT_GATEWAY_REPLICATION_URL must be a valid HTTP URL")
            })
            .transpose()?;
        let replication_token = env::var("JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN")
            .ok()
            .map(|value| SecretToken::parse("JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN", value))
            .transpose()?;
        if replication_token
            .as_ref()
            .is_some_and(|token| token.expose() == management_token.trim())
        {
            anyhow::bail!("Agent Gateway replication token must not reuse the management token");
        }
        let hot_standby_min_acks = env_u32(
            "JOYSAFETER_AGENT_GATEWAY_HOT_STANDBY_MIN_ACKS",
            DEFAULT_HOT_STANDBY_MIN_ACKS,
        )? as usize;
        let replication_ack_timeout = Duration::from_millis(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_REPLICATION_ACK_TIMEOUT_MS",
            DEFAULT_REPLICATION_ACK_TIMEOUT_MS,
        )?);
        let node_visibility = match env::var("JOYSAFETER_AGENT_GATEWAY_NODE_VISIBILITY")
            .unwrap_or_else(|_| "node_scoped".to_string())
            .trim()
            .to_ascii_lowercase()
            .as_str()
        {
            "node_scoped" => NodeVisibility::NodeScoped,
            "unscoped" => NodeVisibility::Unscoped,
            value => anyhow::bail!(
                "JOYSAFETER_AGENT_GATEWAY_NODE_VISIBILITY must be node_scoped or unscoped, got {value:?}"
            ),
        };
        let delivery_timeout = Duration::from_secs(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_DELIVERY_TIMEOUT_SECS",
            DEFAULT_DELIVERY_TIMEOUT_SECS,
        )?);
        let shutdown_grace = Duration::from_secs(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_SHUTDOWN_GRACE_SECS",
            DEFAULT_SHUTDOWN_GRACE_SECS,
        )?);

        Self {
            instance_id,
            xds_addr: socket_addr(&xds_host, xds_port, "xDS")?,
            http_addr: socket_addr(&http_host, http_port, "HTTP")?,
            management_grpc_addr: socket_addr(&http_host, management_grpc_port, "management gRPC")?,
            xds_auth_keyring: XdsAuthKeyring::parse(&keyring, &write_key_id)?,
            management_authenticator: ManagementAuthenticator::new(&management_token)?,
            management_token: SecretToken(management_token.clone()),
            leader_election_enabled,
            k8s_namespace,
            pod_name,
            leader_lease_name,
            leader_identity,
            leader_lease_duration,
            leader_renew_interval,
            replication_url,
            replication_token,
            hot_standby_min_acks,
            replication_ack_timeout,
            node_visibility,
            delivery_timeout,
            shutdown_grace,
            policy_stream_endpoint: env::var("JOYSAFETER_AGENT_GATEWAY_POLICY_STREAM_ENDPOINT")
                .ok()
                .filter(|value| !value.trim().is_empty()),
        }
        .validate()
    }

    fn validate(mut self) -> anyhow::Result<Self> {
        self.instance_id = self.instance_id.trim().to_string();
        if self.instance_id.is_empty() || self.instance_id.len() > 128 {
            anyhow::bail!("agent gateway instance id must contain between 1 and 128 characters");
        }
        if self.xds_addr == self.http_addr {
            anyhow::bail!("Agent Gateway xDS and HTTP listeners must use different addresses");
        }
        if self.leader_election_enabled && self.pod_name.is_none() {
            anyhow::bail!("POD_NAME is required when Agent Gateway leader election is enabled");
        }
        if self.leader_election_enabled
            && (self.replication_url.is_none() || self.replication_token.is_none())
        {
            anyhow::bail!(
                "replication URL and token are required when Agent Gateway leader election is enabled"
            );
        }
        if let Some(url) = &self.replication_url {
            if !matches!(url.scheme(), "http" | "https") || url.cannot_be_a_base() {
                anyhow::bail!("Agent Gateway replication URL must be an HTTP base URL");
            }
        }
        if self.hot_standby_min_acks > 32 {
            anyhow::bail!("Agent Gateway hot-standby minimum ACKs must not exceed 32");
        }
        if !(Duration::from_millis(100)..=Duration::from_secs(30))
            .contains(&self.replication_ack_timeout)
        {
            anyhow::bail!("Agent Gateway replication ACK timeout must be between 100ms and 30s");
        }
        if self.leader_renew_interval.is_zero()
            || self.leader_renew_interval >= self.leader_lease_duration
        {
            anyhow::bail!("Agent Gateway leader renew interval must be lower than lease duration");
        }
        if !(Duration::from_secs(1)..=Duration::from_secs(300)).contains(&self.delivery_timeout) {
            anyhow::bail!("Agent Gateway delivery timeout must be between 1s and 300s");
        }
        if !(Duration::from_secs(1)..=Duration::from_secs(60)).contains(&self.shutdown_grace) {
            anyhow::bail!("Agent Gateway shutdown grace must be between 1s and 60s");
        }
        Ok(self)
    }
}

fn env_u16(name: &str, default: u16) -> anyhow::Result<u16> {
    match env::var(name) {
        Ok(value) => value
            .parse::<u16>()
            .with_context(|| format!("{name} must be a valid TCP port")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("failed to read {name}")),
    }
}

fn env_u32(name: &str, default: u32) -> anyhow::Result<u32> {
    match env::var(name) {
        Ok(value) => value
            .parse::<u32>()
            .with_context(|| format!("{name} must be a valid positive integer")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("failed to read {name}")),
    }
}

fn env_u64(name: &str, default: u64) -> anyhow::Result<u64> {
    match env::var(name) {
        Ok(value) => value
            .parse::<u64>()
            .with_context(|| format!("{name} must be a valid positive integer")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("failed to read {name}")),
    }
}

fn env_bool(name: &str, default: bool) -> anyhow::Result<bool> {
    match env::var(name) {
        Ok(value) => value
            .parse::<bool>()
            .with_context(|| format!("{name} must be true or false")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(error).with_context(|| format!("failed to read {name}")),
    }
}

fn socket_addr(host: &str, port: u16, label: &str) -> anyhow::Result<SocketAddr> {
    let ip = host
        .parse::<IpAddr>()
        .with_context(|| format!("Agent Gateway {label} host must be an IP address"))?;
    Ok(SocketAddr::new(ip, port))
}

#[cfg(test)]
#[path = "../tests/unit/config_test.rs"]
mod tests;
