use std::collections::{HashMap, HashSet};
use std::fmt;
use std::net::IpAddr;

use serde::Serialize;
use sha2::{Digest, Sha256};
use thiserror::Error;
use url::Url;

use crate::grpc::proto;
use crate::ids::{AgentId, CredentialId, SessionId};
use crate::kernel::credentials::access::{
    CredentialAccessContext, CredentialMaterialAccessService,
};
use crate::kernel::credentials::mcp::{McpHeaderInjection, ResolvedMcpCredential};
use crate::kernel::credentials::record::{McpCredentialMetadataRecord, ProjectId};
use crate::kernel::mcp_network_policy::{
    resolve_vetted_addresses_with, McpAddressResolver, McpNetworkPolicy, McpNetworkPolicyError,
    SystemMcpAddressResolver,
};
use crate::kernel::mcp_url;
use crate::sandbox::lds_backend::{
    EgressCredentialRoute, EgressExposure, EgressKind, MCP_EGRESS_HOST,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EffectiveNetworkMode {
    Limited,
    Unrestricted,
    Disabled,
}

pub fn effective_network_mode(
    networking: Option<&serde_json::Value>,
    envoy_enabled: bool,
) -> Result<EffectiveNetworkMode, McpRuntimePlanError> {
    let configured =
        networking.and_then(|value| value.get("type").and_then(|value| value.as_str()));
    match configured {
        Some("limited") => Ok(EffectiveNetworkMode::Limited),
        Some("unrestricted") => Ok(EffectiveNetworkMode::Unrestricted),
        Some("disabled") => Ok(EffectiveNetworkMode::Disabled),
        Some(other) => Err(McpRuntimePlanError::UnsupportedNetworkMode {
            mode: other.to_string(),
        }),
        None if envoy_enabled => Ok(EffectiveNetworkMode::Limited),
        None => Ok(EffectiveNetworkMode::Unrestricted),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum McpTransport {
    StreamableHttp,
    Sse,
    LocalStdio,
}

impl McpTransport {
    fn parse(value: &str) -> Result<Self, McpRuntimePlanError> {
        match value {
            "streamable_http" => Ok(Self::StreamableHttp),
            "sse" => Ok(Self::Sse),
            "local_stdio" => Ok(Self::LocalStdio),
            other => Err(McpRuntimePlanError::UnsupportedTransport {
                transport: other.to_string(),
            }),
        }
    }

    fn runner_value(self) -> &'static str {
        match self {
            Self::StreamableHttp => "streamable_http",
            Self::Sse => "sse",
            Self::LocalStdio => "local_stdio",
        }
    }

    fn proto_value(self) -> i32 {
        match self {
            Self::StreamableHttp => proto::McpTransport::StreamableHttp as i32,
            Self::Sse => proto::McpTransport::Sse as i32,
            Self::LocalStdio => proto::McpTransport::LocalStdio as i32,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum McpAuthRequirement {
    Required,
    Optional,
    None,
}

impl McpAuthRequirement {
    fn parse(value: Option<&str>) -> Result<Self, McpRuntimePlanError> {
        match value {
            Some("required") => Ok(Self::Required),
            Some("optional") => Ok(Self::Optional),
            Some("none") => Ok(Self::None),
            None | Some("") => Err(McpRuntimePlanError::MissingAuthRequirement),
            Some(other) => Err(McpRuntimePlanError::UnsupportedAuthRequirement {
                requirement: other.to_string(),
            }),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct McpEndpoint {
    pub original_url: String,
    pub normalized_url: String,
    pub host: String,
    pub port: u16,
    pub upstream_prefix: String,
    pub query: Option<String>,
    pub tls: bool,
    pub vetted_addresses: Vec<IpAddr>,
}

#[derive(Clone, PartialEq, Eq, Serialize)]
pub struct ResolvedLocalCommand {
    pub command: String,
    pub args: Vec<String>,
    pub env: HashMap<String, String>,
}

impl fmt::Debug for ResolvedLocalCommand {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedLocalCommand")
            .field("command", &self.command)
            .field("args", &self.args)
            .field("env_keys", &self.env.keys().collect::<Vec<_>>())
            .finish()
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct ResolvedMcpServer {
    pub server_id: String,
    pub route_key: String,
    pub display_name: String,
    pub transport: McpTransport,
    pub original_endpoint: Option<McpEndpoint>,
    pub sandbox_endpoint: Option<String>,
    pub local_command: Option<ResolvedLocalCommand>,
    pub auth_requirement: McpAuthRequirement,
    pub credential_id: Option<CredentialId>,
    pub injection: Option<McpHeaderInjection>,
}

impl fmt::Debug for ResolvedMcpServer {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedMcpServer")
            .field("server_id", &self.server_id)
            .field("route_key", &self.route_key)
            .field("display_name", &self.display_name)
            .field("transport", &self.transport)
            .field("original_endpoint", &self.original_endpoint)
            .field("sandbox_endpoint", &self.sandbox_endpoint)
            .field("local_command", &self.local_command)
            .field("auth_requirement", &self.auth_requirement)
            .field("credential_id", &self.credential_id)
            .field("injection", &self.injection.as_ref().map(|_| "<redacted>"))
            .finish()
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct ResolvedMcpRuntimePlan {
    pub runtime_generation: i64,
    pub harness_revision: String,
    pub egress_revision: String,
    pub servers: Vec<ResolvedMcpServer>,
}

impl fmt::Debug for ResolvedMcpRuntimePlan {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedMcpRuntimePlan")
            .field("runtime_generation", &self.runtime_generation)
            .field("harness_revision", &self.harness_revision)
            .field("egress_revision", &self.egress_revision)
            .field("servers", &self.servers)
            .finish()
    }
}

impl ResolvedMcpRuntimePlan {
    pub fn runner_servers(&self) -> Vec<proto::McpConfig> {
        self.servers
            .iter()
            .map(
                |server| match (&server.original_endpoint, &server.local_command) {
                    (Some(_), None) => proto::McpConfig {
                        name: server.display_name.clone(),
                        transport: server.transport.proto_value(),
                        url: server.sandbox_endpoint.clone().unwrap_or_default(),
                        ..Default::default()
                    },
                    (None, Some(command)) => proto::McpConfig {
                        name: server.display_name.clone(),
                        command: command.command.clone(),
                        args: command.args.clone(),
                        env: command.env.clone(),
                        transport: server.transport.proto_value(),
                        ..Default::default()
                    },
                    _ => unreachable!("validated MCP plan has exactly one transport payload"),
                },
            )
            .collect()
    }

    pub fn egress_routes(&self) -> Vec<EgressCredentialRoute> {
        self.servers
            .iter()
            .filter_map(|server| {
                let endpoint = server.original_endpoint.as_ref()?;
                let sandbox_endpoint = server.sandbox_endpoint.as_ref()?;
                if !sandbox_endpoint.starts_with(&format!("http://{MCP_EGRESS_HOST}/")) {
                    return None;
                }
                let (inject_headers, remove_headers) = match server.injection.as_ref() {
                    Some(injection) => (
                        vec![(
                            injection.header_name.clone(),
                            injection.header_value.clone(),
                        )],
                        injection.remove_headers.clone(),
                    ),
                    None => (
                        Vec::new(),
                        vec!["authorization".to_string(), "x-api-key".to_string()],
                    ),
                };
                Some(EgressCredentialRoute {
                    id: format!("mcp:{}", server.route_key),
                    kind: EgressKind::Mcp,
                    exposure: EgressExposure::Placeholder,
                    match_host: MCP_EGRESS_HOST.to_string(),
                    match_prefix: format!("/r/{}/", server.route_key),
                    exact_path: false,
                    upstream_host: endpoint.host.clone(),
                    upstream_port: endpoint.port,
                    upstream_prefix: endpoint.upstream_prefix.clone(),
                    upstream_tls: endpoint.tls,
                    cluster_name: String::new(),
                    vetted_addresses: endpoint
                        .vetted_addresses
                        .iter()
                        .map(ToString::to_string)
                        .collect(),
                    inject_headers,
                    remove_headers,
                })
            })
            .collect()
    }
}

#[derive(Debug, Clone, Error, PartialEq, Eq)]
pub enum McpRuntimePlanError {
    #[error("unsupported sandbox networking mode: {mode}")]
    UnsupportedNetworkMode { mode: String },
    #[error("MCP server configuration must be an array")]
    InvalidCollection,
    #[error("MCP server entry is invalid")]
    InvalidServer,
    #[error("MCP server name is missing")]
    MissingName,
    #[error("duplicate MCP server name: {server_name}")]
    DuplicateName { server_name: String },
    #[error("unsupported MCP transport: {transport}")]
    UnsupportedTransport { transport: String },
    #[error("MCP transport is missing")]
    MissingTransport,
    #[error("remote MCP authentication requirement is missing")]
    MissingAuthRequirement,
    #[error("unsupported MCP authentication requirement: {requirement}")]
    UnsupportedAuthRequirement { requirement: String },
    #[error("remote MCP server URL is invalid: {server_name}")]
    InvalidRemoteUrl { server_name: String },
    #[error("local MCP server command is invalid: {server_name}")]
    InvalidLocalCommand { server_name: String },
    #[error("MCP server contains a noncanonical field: {server_name}.{field}")]
    NoncanonicalServerField { server_name: String, field: String },
    #[error("required MCP credential is missing: {server_name}")]
    RequiredCredentialMissing { server_name: String },
    #[error("duplicate MCP credential for endpoint: {normalized_url}")]
    DuplicateCredential { normalized_url: String },
    #[error("MCP credential injection requires limited networking: {server_name}")]
    CredentialInjectionRequiresLimitedNetwork { server_name: String },
    #[error("remote MCP networking is disabled: {server_name}")]
    RemoteNetworkingDisabled { server_name: String },
    #[error(transparent)]
    NetworkPolicy(#[from] McpNetworkPolicyError),
}

#[derive(Clone)]
struct McpCredentialBinding {
    id: CredentialId,
    normalized_server_url: String,
    injection: Option<McpHeaderInjection>,
}

fn route_identity(
    agent_id: AgentId,
    ordinal: usize,
    transport: McpTransport,
    name: &str,
    endpoint_or_command: &str,
) -> (String, String) {
    let mut hasher = Sha256::new();
    for part in [
        agent_id.to_string(),
        ordinal.to_string(),
        transport.runner_value().to_string(),
        name.to_string(),
        endpoint_or_command.to_string(),
    ] {
        hasher.update((part.len() as u64).to_be_bytes());
        hasher.update(part.as_bytes());
    }
    let server_id = hex::encode(hasher.finalize());
    let route_key = server_id[..32].to_string();
    (server_id, route_key)
}

fn remote_endpoint(name: &str, raw_url: &str) -> Result<McpEndpoint, McpRuntimePlanError> {
    let parsed = Url::parse(raw_url).map_err(|_| McpRuntimePlanError::InvalidRemoteUrl {
        server_name: name.to_string(),
    })?;
    if !matches!(parsed.scheme(), "http" | "https")
        || parsed.host_str().is_none()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.fragment().is_some()
    {
        return Err(McpRuntimePlanError::InvalidRemoteUrl {
            server_name: name.to_string(),
        });
    }
    let tls = parsed.scheme() == "https";
    let port =
        parsed
            .port_or_known_default()
            .ok_or_else(|| McpRuntimePlanError::InvalidRemoteUrl {
                server_name: name.to_string(),
            })?;
    let path = if parsed.path().is_empty() {
        "/"
    } else {
        parsed.path()
    };
    let upstream_prefix = if path.ends_with('/') {
        path.to_string()
    } else {
        format!("{path}/")
    };
    Ok(McpEndpoint {
        original_url: raw_url.trim().to_string(),
        normalized_url: mcp_url::normalize(raw_url),
        host: parsed.host_str().unwrap_or_default().to_string(),
        port,
        upstream_prefix,
        query: parsed.query().map(ToOwned::to_owned),
        tls,
        vetted_addresses: Vec::new(),
    })
}

pub async fn apply_mcp_network_policy(
    plan: &mut ResolvedMcpRuntimePlan,
    resolver: &dyn McpAddressResolver,
    policy: &McpNetworkPolicy,
) -> Result<(), McpRuntimePlanError> {
    let mut resolved = HashMap::<(String, u16), Vec<IpAddr>>::new();
    for server in &mut plan.servers {
        let Some(endpoint) = server.original_endpoint.as_mut() else {
            continue;
        };
        let key = (endpoint.host.clone(), endpoint.port);
        endpoint.vetted_addresses = if let Some(addresses) = resolved.get(&key) {
            addresses.clone()
        } else {
            let addresses =
                resolve_vetted_addresses_with(resolver, &endpoint.host, endpoint.port, policy)
                    .await?;
            resolved.insert(key, addresses.clone());
            addresses
        };
    }
    plan.egress_revision = egress_revision(&plan.harness_revision, &plan.servers);
    Ok(())
}

pub fn resolve_mcp_runtime_plan(
    agent_id: AgentId,
    runtime_generation: i64,
    network_mode: EffectiveNetworkMode,
    raw_servers: Option<&serde_json::Value>,
    credentials: &[ResolvedMcpCredential],
) -> Result<ResolvedMcpRuntimePlan, McpRuntimePlanError> {
    let bindings = credentials
        .iter()
        .map(|credential| McpCredentialBinding {
            id: credential.id,
            normalized_server_url: credential.normalized_server_url.clone(),
            injection: Some(credential.injection.clone()),
        })
        .collect::<Vec<_>>();
    resolve_mcp_runtime_plan_from_bindings(
        agent_id,
        runtime_generation,
        network_mode,
        raw_servers,
        &bindings,
    )
}

pub fn resolve_mcp_runtime_plan_from_metadata(
    agent_id: AgentId,
    runtime_generation: i64,
    network_mode: EffectiveNetworkMode,
    raw_servers: Option<&serde_json::Value>,
    credentials: &[McpCredentialMetadataRecord],
) -> Result<ResolvedMcpRuntimePlan, McpRuntimePlanError> {
    let bindings = credentials
        .iter()
        .map(|credential| McpCredentialBinding {
            id: credential.id,
            normalized_server_url: credential.normalized_server_url.clone(),
            injection: None,
        })
        .collect::<Vec<_>>();
    resolve_mcp_runtime_plan_from_bindings(
        agent_id,
        runtime_generation,
        network_mode,
        raw_servers,
        &bindings,
    )
}

pub async fn resolve_mcp_runtime_plan_with_access(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    project_id: Option<&str>,
    session_id: Option<SessionId>,
    agent_id: AgentId,
    runtime_generation: i64,
    network_mode: EffectiveNetworkMode,
    raw_servers: Option<&serde_json::Value>,
) -> anyhow::Result<ResolvedMcpRuntimePlan> {
    resolve_mcp_runtime_plan_with_access_and_resolver(
        credential_access,
        access_context,
        project_id,
        session_id,
        agent_id,
        runtime_generation,
        network_mode,
        raw_servers,
        &SystemMcpAddressResolver,
        &McpNetworkPolicy::from_env(),
    )
    .await
}

pub(crate) async fn resolve_mcp_runtime_plan_with_access_and_resolver(
    credential_access: &CredentialMaterialAccessService,
    access_context: &CredentialAccessContext,
    project_id: Option<&str>,
    session_id: Option<SessionId>,
    agent_id: AgentId,
    runtime_generation: i64,
    network_mode: EffectiveNetworkMode,
    raw_servers: Option<&serde_json::Value>,
    resolver: &dyn McpAddressResolver,
    policy: &McpNetworkPolicy,
) -> anyhow::Result<ResolvedMcpRuntimePlan> {
    let mut plan = if let (Some(project_id), Some(session_id)) = (project_id, session_id) {
        let project_id = ProjectId::parse(project_id)?;
        let metadata = credential_access
            .load_mcp_member_metadata(&project_id, session_id)
            .await?;
        let metadata_plan = resolve_mcp_runtime_plan_from_metadata(
            agent_id,
            runtime_generation,
            network_mode,
            raw_servers,
            &metadata,
        )?;
        let selected_ids = metadata_plan
            .servers
            .iter()
            .filter_map(|server| server.credential_id)
            .collect::<HashSet<_>>();
        let mut resolved = Vec::with_capacity(selected_ids.len());
        for member in metadata
            .iter()
            .filter(|member| selected_ids.contains(&member.id))
        {
            resolved.push(
                credential_access
                    .resolve_mcp_member(&project_id, member, access_context)
                    .await?,
            );
        }
        resolve_mcp_runtime_plan(
            agent_id,
            runtime_generation,
            network_mode,
            raw_servers,
            &resolved,
        )?
    } else {
        resolve_mcp_runtime_plan(agent_id, runtime_generation, network_mode, raw_servers, &[])?
    };
    apply_mcp_network_policy(&mut plan, resolver, policy).await?;
    Ok(plan)
}

fn resolve_mcp_runtime_plan_from_bindings(
    agent_id: AgentId,
    runtime_generation: i64,
    network_mode: EffectiveNetworkMode,
    raw_servers: Option<&serde_json::Value>,
    credentials: &[McpCredentialBinding],
) -> Result<ResolvedMcpRuntimePlan, McpRuntimePlanError> {
    let entries = match raw_servers {
        None => &[][..],
        Some(value) => value
            .as_array()
            .map(Vec::as_slice)
            .ok_or(McpRuntimePlanError::InvalidCollection)?,
    };
    let mut credentials_by_url: HashMap<&str, Vec<&McpCredentialBinding>> = HashMap::new();
    for credential in credentials {
        let bucket = credentials_by_url
            .entry(credential.normalized_server_url.as_str())
            .or_default();
        if bucket.iter().all(|existing| existing.id != credential.id) {
            bucket.push(credential);
        }
    }

    let mut names = HashSet::new();
    let mut servers = Vec::with_capacity(entries.len());
    for (ordinal, entry) in entries.iter().enumerate() {
        let object = entry
            .as_object()
            .ok_or(McpRuntimePlanError::InvalidServer)?;
        let name = object
            .get("name")
            .and_then(|value| value.as_str())
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .ok_or(McpRuntimePlanError::MissingName)?;
        if !names.insert(name.to_string()) {
            return Err(McpRuntimePlanError::DuplicateName {
                server_name: name.to_string(),
            });
        }
        let transport = McpTransport::parse(
            object
                .get("type")
                .and_then(|value| value.as_str())
                .ok_or(McpRuntimePlanError::MissingTransport)?,
        )?;

        if transport == McpTransport::LocalStdio {
            if let Some(field) = object.keys().find(|field| {
                !matches!(field.as_str(), "type" | "name" | "command" | "args" | "env")
            }) {
                return Err(McpRuntimePlanError::NoncanonicalServerField {
                    server_name: name.to_string(),
                    field: field.clone(),
                });
            }
            let command = object
                .get("command")
                .and_then(|value| value.as_str())
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .ok_or_else(|| McpRuntimePlanError::InvalidLocalCommand {
                    server_name: name.to_string(),
                })?;
            if object.get("url").is_some() || object.get("auth_requirement").is_some() {
                return Err(McpRuntimePlanError::InvalidLocalCommand {
                    server_name: name.to_string(),
                });
            }
            let args = match object.get("args") {
                None => Vec::new(),
                Some(value) => value
                    .as_array()
                    .and_then(|values| {
                        values
                            .iter()
                            .map(|value| value.as_str().map(ToOwned::to_owned))
                            .collect::<Option<Vec<_>>>()
                    })
                    .ok_or_else(|| McpRuntimePlanError::NoncanonicalServerField {
                        server_name: name.to_string(),
                        field: "args".to_string(),
                    })?,
            };
            let env = match object.get("env") {
                None => HashMap::new(),
                Some(value) => value
                    .as_object()
                    .and_then(|values| {
                        values
                            .iter()
                            .map(|(key, value)| {
                                value.as_str().map(|value| (key.clone(), value.to_string()))
                            })
                            .collect::<Option<HashMap<_, _>>>()
                    })
                    .ok_or_else(|| McpRuntimePlanError::NoncanonicalServerField {
                        server_name: name.to_string(),
                        field: "env".to_string(),
                    })?,
            };
            let (server_id, route_key) =
                route_identity(agent_id, ordinal, transport, name, command);
            servers.push(ResolvedMcpServer {
                server_id,
                route_key,
                display_name: name.to_string(),
                transport,
                original_endpoint: None,
                sandbox_endpoint: None,
                local_command: Some(ResolvedLocalCommand {
                    command: command.to_string(),
                    args,
                    env,
                }),
                auth_requirement: McpAuthRequirement::None,
                credential_id: None,
                injection: None,
            });
            continue;
        }

        if network_mode == EffectiveNetworkMode::Disabled {
            return Err(McpRuntimePlanError::RemoteNetworkingDisabled {
                server_name: name.to_string(),
            });
        }
        if let Some(field) = object
            .keys()
            .find(|field| !matches!(field.as_str(), "type" | "name" | "url" | "auth_requirement"))
        {
            return Err(McpRuntimePlanError::NoncanonicalServerField {
                server_name: name.to_string(),
                field: field.clone(),
            });
        }
        let raw_url = object
            .get("url")
            .and_then(|value| value.as_str())
            .ok_or_else(|| McpRuntimePlanError::InvalidRemoteUrl {
                server_name: name.to_string(),
            })?;
        let endpoint = remote_endpoint(name, raw_url)?;
        let auth_requirement = McpAuthRequirement::parse(
            object
                .get("auth_requirement")
                .and_then(|value| value.as_str()),
        )?;
        let matching_credentials = credentials_by_url
            .get(endpoint.normalized_url.as_str())
            .map(Vec::as_slice)
            .unwrap_or_default();
        if matching_credentials.len() > 1 {
            return Err(McpRuntimePlanError::DuplicateCredential {
                normalized_url: endpoint.normalized_url.clone(),
            });
        }
        let matching_credential = matching_credentials.first().copied();
        let credential = match auth_requirement {
            McpAuthRequirement::None => None,
            McpAuthRequirement::Optional => matching_credential,
            McpAuthRequirement::Required => Some(matching_credential.ok_or_else(|| {
                McpRuntimePlanError::RequiredCredentialMissing {
                    server_name: name.to_string(),
                }
            })?),
        };
        if credential.is_some() && network_mode != EffectiveNetworkMode::Limited {
            return Err(
                McpRuntimePlanError::CredentialInjectionRequiresLimitedNetwork {
                    server_name: name.to_string(),
                },
            );
        }

        let (server_id, route_key) =
            route_identity(agent_id, ordinal, transport, name, &endpoint.normalized_url);
        let sandbox_endpoint = match network_mode {
            EffectiveNetworkMode::Limited => Some(format!(
                "http://{MCP_EGRESS_HOST}/r/{route_key}/{}",
                endpoint
                    .query
                    .as_ref()
                    .map(|query| format!("?{query}"))
                    .unwrap_or_default()
            )),
            EffectiveNetworkMode::Unrestricted => Some(endpoint.original_url.clone()),
            EffectiveNetworkMode::Disabled => unreachable!(),
        };
        servers.push(ResolvedMcpServer {
            server_id,
            route_key,
            display_name: name.to_string(),
            transport,
            original_endpoint: Some(endpoint),
            sandbox_endpoint,
            local_command: None,
            auth_requirement,
            credential_id: credential.map(|credential| credential.id),
            injection: credential.and_then(|credential| credential.injection.clone()),
        });
    }

    let runner_servers = servers
        .iter()
        .map(|server| {
            serde_json::json!({
                "server_id": server.server_id,
                "name": server.display_name,
                "transport": server.transport.runner_value(),
                "sandbox_endpoint": server.sandbox_endpoint,
                "local_command": server.local_command,
            })
        })
        .collect::<Vec<_>>();
    let harness_revision = hex::encode(Sha256::digest(
        serde_json::to_vec(&runner_servers).expect("MCP runner projection is serializable"),
    ));
    let egress_revision = egress_revision(&harness_revision, &servers);

    Ok(ResolvedMcpRuntimePlan {
        runtime_generation,
        harness_revision,
        egress_revision,
        servers,
    })
}

fn egress_revision(harness_revision: &str, servers: &[ResolvedMcpServer]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(harness_revision.as_bytes());
    for server in servers {
        if let Some(endpoint) = &server.original_endpoint {
            hasher.update(endpoint.normalized_url.as_bytes());
            for address in &endpoint.vetted_addresses {
                hasher.update(address.to_string().as_bytes());
            }
        }
        if let Some(injection) = &server.injection {
            hasher.update(injection.header_name.as_bytes());
            hasher.update(injection.header_value.as_bytes());
        }
    }
    hex::encode(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeSet, HashMap};
    use std::net::IpAddr;

    use uuid::Uuid;

    use crate::grpc::proto::McpTransport as ProtoMcpTransport;
    use crate::ids::{AgentId, CredentialGroupId, CredentialId};
    use crate::kernel::credentials::mcp::{McpHeaderInjection, ResolvedMcpCredential};
    use crate::kernel::credentials::record::{McpCredentialMetadataRecord, ProjectId};
    use crate::kernel::mcp_network_policy::{
        McpAddressResolver, McpNetworkPolicy, McpNetworkPolicyError,
    };

    use super::{
        apply_mcp_network_policy, effective_network_mode, resolve_mcp_runtime_plan,
        resolve_mcp_runtime_plan_from_metadata, EffectiveNetworkMode, McpAuthRequirement,
        McpRuntimePlanError, McpTransport,
    };

    struct StaticResolver {
        addresses: HashMap<String, Vec<IpAddr>>,
    }

    #[async_trait::async_trait]
    impl McpAddressResolver for StaticResolver {
        async fn resolve(
            &self,
            host: &str,
            _port: u16,
        ) -> Result<Vec<IpAddr>, McpNetworkPolicyError> {
            self.addresses.get(host).cloned().ok_or_else(|| {
                McpNetworkPolicyError::ResolutionFailed {
                    host: host.to_string(),
                }
            })
        }
    }

    fn credential(url: &str, header_name: &str, header_value: &str) -> ResolvedMcpCredential {
        ResolvedMcpCredential {
            id: CredentialId::from_uuid(Uuid::nil()),
            server_url: url.to_string(),
            normalized_server_url: crate::kernel::mcp_url::normalize(url),
            auth_scheme: "custom_header".to_string(),
            injection: McpHeaderInjection {
                header_name: header_name.to_string(),
                header_value: header_value.to_string(),
                remove_headers: vec![
                    "authorization".to_string(),
                    "x-api-key".to_string(),
                    header_name.to_string(),
                ],
            },
        }
    }

    fn credential_metadata(url: &str) -> McpCredentialMetadataRecord {
        McpCredentialMetadataRecord {
            id: CredentialId::from_uuid(Uuid::nil()),
            project_id: ProjectId::parse("project-1").unwrap(),
            group_id: CredentialGroupId::from_uuid(Uuid::nil()),
            server_url: url.to_string(),
            normalized_server_url: crate::kernel::mcp_url::normalize(url),
            auth_scheme: "static_bearer".to_string(),
            material_fields: BTreeSet::from(["token_value".to_string()]),
        }
    }

    #[test]
    fn metadata_plan_selects_required_credential_without_material() {
        let raw = serde_json::json!([{
            "type": "streamable_http",
            "name": "private",
            "url": "https://example.com/mcp",
            "auth_requirement": "required"
        }]);

        let plan = resolve_mcp_runtime_plan_from_metadata(
            AgentId::from_uuid(Uuid::nil()),
            7,
            EffectiveNetworkMode::Limited,
            Some(&raw),
            &[credential_metadata("https://example.com/mcp")],
        )
        .unwrap();

        assert_eq!(
            plan.servers[0].credential_id,
            Some(CredentialId::from_uuid(Uuid::nil()))
        );
        assert!(plan.servers[0].injection.is_none());
        assert!(plan.runner_servers()[0]
            .url
            .starts_with("http://mcp-egress.internal/r/"));
        assert!(plan.egress_routes()[0].inject_headers.is_empty());
    }

    #[test]
    fn unrelated_duplicate_credentials_do_not_block_the_plan() {
        let raw = serde_json::json!([{
            "type": "streamable_http",
            "name": "selected",
            "url": "https://selected.example/mcp",
            "auth_requirement": "required"
        }]);
        let mut selected = credential_metadata("https://selected.example/mcp");
        selected.id = CredentialId::from_uuid(Uuid::from_u128(1));
        let mut unused_a = credential_metadata("https://unused.example/mcp");
        unused_a.id = CredentialId::from_uuid(Uuid::from_u128(2));
        let mut unused_b = credential_metadata("https://unused.example/mcp/");
        unused_b.id = CredentialId::from_uuid(Uuid::from_u128(3));

        let plan = resolve_mcp_runtime_plan_from_metadata(
            AgentId::from_uuid(Uuid::nil()),
            1,
            EffectiveNetworkMode::Limited,
            Some(&raw),
            &[selected, unused_a, unused_b],
        )
        .unwrap();

        assert_eq!(
            plan.servers[0].credential_id,
            Some(CredentialId::from_uuid(Uuid::from_u128(1)))
        );
    }

    #[test]
    fn effective_network_mode_uses_environment_before_envoy_default() {
        assert_eq!(
            effective_network_mode(Some(&serde_json::json!({"type": "limited"})), false).unwrap(),
            EffectiveNetworkMode::Limited
        );
        assert_eq!(
            effective_network_mode(Some(&serde_json::json!({"net_type": "unrestricted"})), true)
                .unwrap(),
            EffectiveNetworkMode::Limited
        );
        assert_eq!(
            effective_network_mode(Some(&serde_json::json!({"type": "disabled"})), true).unwrap(),
            EffectiveNetworkMode::Disabled
        );
        assert_eq!(
            effective_network_mode(None, true).unwrap(),
            EffectiveNetworkMode::Limited
        );
        assert_eq!(
            effective_network_mode(None, false).unwrap(),
            EffectiveNetworkMode::Unrestricted
        );
        assert!(
            effective_network_mode(Some(&serde_json::json!({"type": "future"})), true).is_err()
        );
    }

    #[test]
    fn one_plan_projects_matching_runner_and_envoy_routes() {
        let raw = serde_json::json!([
            {
                "type": "streamable_http",
                "name": "Unsafe / Display Name",
                "url": "https://mcp.example.com:8443/base/path?tenant=a",
                "auth_requirement": "required"
            },
            {
                "type": "sse",
                "name": "events",
                "url": "http://events.example.com:8765/sse",
                "auth_requirement": "none"
            },
            {
                "type": "local_stdio",
                "name": "local",
                "command": "node",
                "args": ["server.js"],
                "env": {"MODE": "safe"}
            }
        ]);
        let plan = resolve_mcp_runtime_plan(
            AgentId::from_uuid(Uuid::nil()),
            7,
            EffectiveNetworkMode::Limited,
            Some(&raw),
            &[credential(
                "https://mcp.example.com:8443/base/path?tenant=a",
                "x-service-token",
                "Token secret",
            )],
        )
        .unwrap();

        assert_eq!(plan.runtime_generation, 7);
        assert_eq!(plan.servers.len(), 3);
        assert_eq!(plan.servers[0].transport, McpTransport::StreamableHttp);
        assert_eq!(
            plan.servers[0].auth_requirement,
            McpAuthRequirement::Required
        );
        assert_eq!(plan.servers[1].transport, McpTransport::Sse);
        assert_eq!(plan.servers[2].transport, McpTransport::LocalStdio);

        let runner = plan.runner_servers();
        assert_eq!(
            runner[0].transport,
            ProtoMcpTransport::StreamableHttp as i32
        );
        assert!(runner[0].url.starts_with("http://mcp-egress.internal/r/"));
        assert!(runner[0].url.ends_with("/?tenant=a"));
        assert!(!runner[0].url.contains("mcp.example.com"));
        assert!(!runner[0].url.contains("Unsafe"));
        assert!(runner[0].headers.is_empty());
        assert_eq!(runner[1].transport, ProtoMcpTransport::Sse as i32);
        assert_eq!(runner[2].command, "node");
        assert_eq!(runner[2].args, vec!["server.js"]);
        assert_eq!(
            runner[2].env,
            HashMap::from([("MODE".to_string(), "safe".to_string())])
        );

        let routes = plan.egress_routes();
        assert_eq!(routes.len(), 2);
        assert_eq!(routes[0].match_host, "mcp-egress.internal");
        assert!(routes[0].match_prefix.starts_with("/r/"));
        assert!(!routes[0].match_prefix.contains("Unsafe"));
        assert_eq!(routes[0].upstream_host, "mcp.example.com");
        assert_eq!(routes[0].upstream_port, 8443);
        assert_eq!(routes[0].upstream_prefix, "/base/path/");
        assert!(routes[0].upstream_tls);
        assert_eq!(routes[0].inject_headers[0].0, "x-service-token");
        assert_eq!(routes[0].inject_headers[0].1, "Token secret");
        assert!(routes[1].inject_headers.is_empty());
    }

    #[tokio::test]
    async fn activation_pins_addresses_without_changing_runner_projection() {
        let raw = serde_json::json!([{
            "type": "streamable_http",
            "name": "remote",
            "url": "https://mcp.example.com:8443/base?tenant=a",
            "auth_requirement": "none"
        }]);
        let mut plan = resolve_mcp_runtime_plan(
            AgentId::from_uuid(Uuid::nil()),
            3,
            EffectiveNetworkMode::Limited,
            Some(&raw),
            &[],
        )
        .unwrap();
        let runner_before = plan.runner_servers();
        let egress_revision_before = plan.egress_revision.clone();
        let resolver = StaticResolver {
            addresses: HashMap::from([(
                "mcp.example.com".to_string(),
                vec![
                    "203.0.113.11".parse().unwrap(),
                    "203.0.113.10".parse().unwrap(),
                ],
            )]),
        };

        apply_mcp_network_policy(&mut plan, &resolver, &McpNetworkPolicy::default())
            .await
            .unwrap();

        assert_eq!(plan.runner_servers(), runner_before);
        assert_ne!(plan.egress_revision, egress_revision_before);
        assert_eq!(
            plan.servers[0]
                .original_endpoint
                .as_ref()
                .unwrap()
                .vetted_addresses,
            vec![
                "203.0.113.10".parse::<IpAddr>().unwrap(),
                "203.0.113.11".parse::<IpAddr>().unwrap(),
            ]
        );
        assert_eq!(
            plan.egress_routes()[0].vetted_addresses,
            vec!["203.0.113.10".to_string(), "203.0.113.11".to_string()]
        );
    }

    #[test]
    fn legacy_transport_and_missing_auth_are_rejected_after_cutover() {
        let raw = serde_json::json!([
            {"type": "url", "name": "legacy", "url": "https://example.com/mcp"}
        ]);

        let error = resolve_mcp_runtime_plan(
            AgentId::from_uuid(Uuid::nil()),
            1,
            EffectiveNetworkMode::Limited,
            Some(&raw),
            &[],
        )
        .unwrap_err();
        assert!(matches!(
            error,
            McpRuntimePlanError::UnsupportedTransport { .. }
        ));

        let raw = serde_json::json!([
            {"type": "streamable_http", "name": "missing-auth", "url": "https://example.com/mcp"}
        ]);
        let error = resolve_mcp_runtime_plan(
            AgentId::from_uuid(Uuid::nil()),
            1,
            EffectiveNetworkMode::Limited,
            Some(&raw),
            &[],
        )
        .unwrap_err();
        assert_eq!(error, McpRuntimePlanError::MissingAuthRequirement);
    }

    #[test]
    fn noncanonical_transport_fields_are_rejected_instead_of_ignored() {
        for raw in [
            serde_json::json!([{
                "type": "streamable_http",
                "name": "remote",
                "url": "https://example.com/mcp",
                "auth_requirement": "required",
                "command": null
            }]),
            serde_json::json!([{
                "type": "local_stdio",
                "name": "local",
                "command": "node",
                "args": "--stdio"
            }]),
            serde_json::json!([{
                "type": "local_stdio",
                "name": "local",
                "command": "node",
                "env": []
            }]),
        ] {
            let error = resolve_mcp_runtime_plan(
                AgentId::from_uuid(Uuid::nil()),
                1,
                EffectiveNetworkMode::Limited,
                Some(&raw),
                &[],
            )
            .unwrap_err();
            assert!(matches!(
                error,
                McpRuntimePlanError::NoncanonicalServerField { .. }
            ));
        }
    }

    #[test]
    fn required_auth_without_matching_credential_fails_closed() {
        let raw = serde_json::json!([
            {
                "type": "streamable_http",
                "name": "required",
                "url": "https://example.com/mcp",
                "auth_requirement": "required"
            }
        ]);

        assert_eq!(
            resolve_mcp_runtime_plan(
                AgentId::from_uuid(Uuid::nil()),
                1,
                EffectiveNetworkMode::Limited,
                Some(&raw),
                &[],
            ),
            Err(McpRuntimePlanError::RequiredCredentialMissing {
                server_name: "required".to_string()
            })
        );
    }

    #[test]
    fn duplicate_credentials_for_one_endpoint_fail_closed() {
        let raw = serde_json::json!([
            {
                "type": "streamable_http",
                "name": "duplicate",
                "url": "https://example.com/mcp",
                "auth_requirement": "required"
            }
        ]);
        let credentials = [
            credential("https://example.com/mcp", "authorization", "Bearer one"),
            ResolvedMcpCredential {
                id: CredentialId::from_uuid(Uuid::from_u128(u128::MAX)),
                ..credential("https://example.com/mcp", "authorization", "Bearer two")
            },
        ];

        assert_eq!(
            resolve_mcp_runtime_plan(
                AgentId::from_uuid(Uuid::nil()),
                1,
                EffectiveNetworkMode::Limited,
                Some(&raw),
                &credentials,
            ),
            Err(McpRuntimePlanError::DuplicateCredential {
                normalized_url: "https://example.com/mcp".to_string()
            })
        );
    }

    #[test]
    fn unrestricted_mode_rejects_credential_injection_but_allows_public_remote() {
        let required = serde_json::json!([
            {
                "type": "streamable_http",
                "name": "private",
                "url": "https://example.com/mcp",
                "auth_requirement": "required"
            }
        ]);
        assert_eq!(
            resolve_mcp_runtime_plan(
                AgentId::from_uuid(Uuid::nil()),
                1,
                EffectiveNetworkMode::Unrestricted,
                Some(&required),
                &[credential(
                    "https://example.com/mcp",
                    "authorization",
                    "Bearer secret"
                )],
            ),
            Err(
                McpRuntimePlanError::CredentialInjectionRequiresLimitedNetwork {
                    server_name: "private".to_string()
                }
            )
        );

        let public = serde_json::json!([
            {
                "type": "streamable_http",
                "name": "public",
                "url": "https://public.example.com/mcp",
                "auth_requirement": "none"
            }
        ]);
        let plan = resolve_mcp_runtime_plan(
            AgentId::from_uuid(Uuid::nil()),
            1,
            EffectiveNetworkMode::Unrestricted,
            Some(&public),
            &[],
        )
        .unwrap();
        assert_eq!(
            plan.runner_servers()[0].url,
            "https://public.example.com/mcp"
        );
        assert!(plan.egress_routes().is_empty());
    }

    #[test]
    fn disabled_network_rejects_remote_but_allows_local_stdio() {
        let remote = serde_json::json!([
            {
                "type": "streamable_http",
                "name": "remote",
                "url": "https://example.com/mcp",
                "auth_requirement": "optional"
            }
        ]);
        assert_eq!(
            resolve_mcp_runtime_plan(
                AgentId::from_uuid(Uuid::nil()),
                1,
                EffectiveNetworkMode::Disabled,
                Some(&remote),
                &[],
            ),
            Err(McpRuntimePlanError::RemoteNetworkingDisabled {
                server_name: "remote".to_string()
            })
        );

        let local = serde_json::json!([
            {"type": "local_stdio", "name": "local", "command": "node", "args": []}
        ]);
        let plan = resolve_mcp_runtime_plan(
            AgentId::from_uuid(Uuid::nil()),
            1,
            EffectiveNetworkMode::Disabled,
            Some(&local),
            &[],
        )
        .unwrap();
        assert_eq!(plan.runner_servers()[0].command, "node");
    }
}
