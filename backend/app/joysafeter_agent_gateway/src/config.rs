use std::env;
use std::net::{IpAddr, SocketAddr};
use std::time::Duration;

use anyhow::Context;

use crate::xds::auth::XdsAuthKeyring;
use crate::xds::control_plane::NodeVisibility;

const DEFAULT_XDS_PORT: u16 = 9092;
const DEFAULT_HTTP_PORT: u16 = 9093;
const DEFAULT_MANAGEMENT_GRPC_PORT: u16 = 9094;
const DEFAULT_DELIVERY_TIMEOUT_SECS: u64 = 20;
const DEFAULT_SHUTDOWN_GRACE_SECS: u64 = 10;
const DEFAULT_REPLICATION_ACK_TIMEOUT_MS: u64 = 1_000;
const DEFAULT_HOT_STANDBY_MIN_ACKS: u32 = 1;
const DEFAULT_POLICY_STREAM_MAX_OUTSTANDING: usize = 512;
const DEFAULT_POLICY_STREAM_MAX_CONCURRENCY: usize = 256;
const DEFAULT_POLICY_LANE_QUEUE_CAPACITY: usize = 128;
const DEFAULT_MAX_POLICY_STREAMS: usize = 64;
const DEFAULT_MAX_REPLICATION_STREAMS: usize = 32;
const DEFAULT_REPLICATION_RECONNECT_BASE_DELAY_MS: u64 = 100;
const DEFAULT_REPLICATION_RECONNECT_MAX_DELAY_MS: u64 = 5_000;
const DEFAULT_REPLICATION_KEEPALIVE_INTERVAL_SECS: u64 = 10;
const DEFAULT_REPLICATION_KEEPALIVE_TIMEOUT_SECS: u64 = 5;
const DEFAULT_DNS_CACHE_MAX_HOSTS: u32 = 4_096;
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
    pub management_token: SecretToken,
    pub leader_election_enabled: bool,
    pub k8s_namespace: String,
    pub pod_name: Option<String>,
    pub leader_lease_name: String,
    pub leader_identity: String,
    pub leader_lease_duration: Duration,
    pub leader_renew_interval: Duration,
    pub replication_endpoint: Option<String>,
    pub replication_token: Option<SecretToken>,
    pub hot_standby_min_acks: usize,
    pub replication_ack_timeout: Duration,
    pub policy_stream_max_outstanding: usize,
    pub policy_stream_max_concurrency: usize,
    pub policy_lane_queue_capacity: usize,
    pub max_policy_streams: usize,
    pub max_replication_streams: usize,
    pub replication_reconnect_base_delay: Duration,
    pub replication_reconnect_max_delay: Duration,
    pub replication_keepalive_interval: Duration,
    pub replication_keepalive_timeout: Duration,
    pub node_visibility: NodeVisibility,
    pub delivery_timeout: Duration,
    pub dns_cache_max_hosts: u32,
    pub shutdown_grace: Duration,
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
        let replication_endpoint = env::var("JOYSAFETER_AGENT_GATEWAY_REPLICATION_ENDPOINT")
            .ok()
            .filter(|value| !value.trim().is_empty())
            .map(|value| {
                tonic::transport::Endpoint::from_shared(value.clone())
                    .map(|_| value)
                    .context(
                        "JOYSAFETER_AGENT_GATEWAY_REPLICATION_ENDPOINT must be a valid gRPC endpoint",
                    )
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
        let policy_stream_max_outstanding = env_usize(
            "JOYSAFETER_AGENT_GATEWAY_POLICY_STREAM_MAX_OUTSTANDING",
            DEFAULT_POLICY_STREAM_MAX_OUTSTANDING,
        )?;
        let policy_stream_max_concurrency = env_usize(
            "JOYSAFETER_AGENT_GATEWAY_POLICY_STREAM_MAX_CONCURRENCY",
            DEFAULT_POLICY_STREAM_MAX_CONCURRENCY,
        )?;
        let policy_lane_queue_capacity = env_usize(
            "JOYSAFETER_AGENT_GATEWAY_POLICY_LANE_QUEUE_CAPACITY",
            DEFAULT_POLICY_LANE_QUEUE_CAPACITY,
        )?;
        let max_policy_streams = env_usize(
            "JOYSAFETER_AGENT_GATEWAY_MAX_POLICY_STREAMS",
            DEFAULT_MAX_POLICY_STREAMS,
        )?;
        let max_replication_streams = env_usize(
            "JOYSAFETER_AGENT_GATEWAY_MAX_REPLICATION_STREAMS",
            DEFAULT_MAX_REPLICATION_STREAMS,
        )?;
        let replication_reconnect_base_delay = Duration::from_millis(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_REPLICATION_RECONNECT_BASE_DELAY_MS",
            DEFAULT_REPLICATION_RECONNECT_BASE_DELAY_MS,
        )?);
        let replication_reconnect_max_delay = Duration::from_millis(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_REPLICATION_RECONNECT_MAX_DELAY_MS",
            DEFAULT_REPLICATION_RECONNECT_MAX_DELAY_MS,
        )?);
        let replication_keepalive_interval = Duration::from_secs(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_REPLICATION_KEEPALIVE_INTERVAL_SECS",
            DEFAULT_REPLICATION_KEEPALIVE_INTERVAL_SECS,
        )?);
        let replication_keepalive_timeout = Duration::from_secs(env_u64(
            "JOYSAFETER_AGENT_GATEWAY_REPLICATION_KEEPALIVE_TIMEOUT_SECS",
            DEFAULT_REPLICATION_KEEPALIVE_TIMEOUT_SECS,
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
        let dns_cache_max_hosts = env_u32(
            "JOYSAFETER_AGENT_GATEWAY_DNS_CACHE_MAX_HOSTS",
            DEFAULT_DNS_CACHE_MAX_HOSTS,
        )?;
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
            management_token: SecretToken::parse(
                "JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN",
                management_token,
            )?,
            leader_election_enabled,
            k8s_namespace,
            pod_name,
            leader_lease_name,
            leader_identity,
            leader_lease_duration,
            leader_renew_interval,
            replication_endpoint,
            replication_token,
            hot_standby_min_acks,
            replication_ack_timeout,
            policy_stream_max_outstanding,
            policy_stream_max_concurrency,
            policy_lane_queue_capacity,
            max_policy_streams,
            max_replication_streams,
            replication_reconnect_base_delay,
            replication_reconnect_max_delay,
            replication_keepalive_interval,
            replication_keepalive_timeout,
            node_visibility,
            delivery_timeout,
            dns_cache_max_hosts,
            shutdown_grace,
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
            && (self.replication_endpoint.is_none() || self.replication_token.is_none())
        {
            anyhow::bail!(
                "replication endpoint and token are required when Agent Gateway leader election is enabled"
            );
        }
        if self.hot_standby_min_acks > 32 {
            anyhow::bail!("Agent Gateway hot-standby minimum ACKs must not exceed 32");
        }
        if !(Duration::from_millis(100)..=Duration::from_secs(30))
            .contains(&self.replication_ack_timeout)
        {
            anyhow::bail!("Agent Gateway replication ACK timeout must be between 100ms and 30s");
        }
        if self.policy_stream_max_outstanding == 0
            || self.policy_stream_max_outstanding > 65_536
            || self.policy_stream_max_concurrency == 0
            || self.policy_stream_max_concurrency > self.policy_stream_max_outstanding
        {
            anyhow::bail!(
                "Agent Gateway policy stream limits must satisfy 1 <= concurrency <= outstanding <= 65536"
            );
        }
        if self.policy_lane_queue_capacity == 0 || self.policy_lane_queue_capacity > 4096 {
            anyhow::bail!("Agent Gateway policy lane queue capacity must be between 1 and 4096");
        }
        if self.max_policy_streams == 0 || self.max_policy_streams > 4096 {
            anyhow::bail!("Agent Gateway maximum policy streams must be between 1 and 4096");
        }
        if self.max_replication_streams == 0 || self.max_replication_streams > 1024 {
            anyhow::bail!("Agent Gateway maximum replication streams must be between 1 and 1024");
        }
        if self.replication_reconnect_base_delay.is_zero()
            || self.replication_reconnect_base_delay > self.replication_reconnect_max_delay
            || self.replication_reconnect_max_delay > Duration::from_secs(60)
        {
            anyhow::bail!(
                "Agent Gateway replication reconnect delays must satisfy 1ms <= base <= max <= 60s"
            );
        }
        if self.replication_keepalive_timeout.is_zero()
            || self.replication_keepalive_interval.is_zero()
            || self.replication_keepalive_timeout > self.replication_keepalive_interval
        {
            anyhow::bail!(
                "Agent Gateway replication keepalive must satisfy 1s <= timeout <= interval"
            );
        }
        if self.leader_renew_interval.is_zero()
            || self.leader_renew_interval >= self.leader_lease_duration
        {
            anyhow::bail!("Agent Gateway leader renew interval must be lower than lease duration");
        }
        if !(Duration::from_secs(1)..=Duration::from_secs(300)).contains(&self.delivery_timeout) {
            anyhow::bail!("Agent Gateway delivery timeout must be between 1s and 300s");
        }
        if self.dns_cache_max_hosts == 0 {
            anyhow::bail!("Agent Gateway DNS cache max hosts must be positive");
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

fn env_usize(name: &str, default: usize) -> anyhow::Result<usize> {
    match env::var(name) {
        Ok(value) => value
            .parse::<usize>()
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
