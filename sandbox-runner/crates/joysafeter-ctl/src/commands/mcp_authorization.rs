use crate::client::JoysafeterClient;
use anyhow::{bail, Context};
use dialoguer::{Input, Password, Select};
use joysafeter_entity_id::{AgentId, CredentialGroupId, CredentialId, EnvironmentId};
use serde_json::Value;
use std::collections::HashSet;
use url::Url;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum McpAuthRequirement {
    Required,
    Optional,
    None,
}

#[derive(Clone, Debug)]
pub struct McpEndpoint {
    pub name: String,
    pub url: String,
    pub normalized_url: String,
    pub auth_requirement: McpAuthRequirement,
}

#[derive(Clone, Debug)]
pub struct CredentialGroup {
    pub id: CredentialGroupId,
    pub name: String,
    pub archived: bool,
    pub member_urls: Vec<String>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CoverageStatus {
    Matched,
    OptionalAnonymous,
    NotRequired,
    MissingRequired,
    Ambiguous,
}

#[derive(Clone, Debug)]
pub struct EndpointCoverage {
    pub endpoint: McpEndpoint,
    pub matching_credential_count: usize,
    pub status: CoverageStatus,
}

#[derive(Clone, Debug)]
pub struct CoverageSummary {
    pub endpoints: Vec<EndpointCoverage>,
    pub blocking: bool,
}

#[derive(Clone, Debug, Default)]
pub struct SessionAuthorization {
    pub credential_group_ids: Vec<CredentialGroupId>,
    created_groups: Vec<CredentialGroupId>,
    created_members: Vec<(CredentialGroupId, CredentialId)>,
}

impl SessionAuthorization {
    pub fn from_group_ids(credential_group_ids: &[CredentialGroupId]) -> Self {
        Self {
            credential_group_ids: deduplicate_group_ids(credential_group_ids),
            ..Self::default()
        }
    }

    pub async fn rollback_created(&mut self, client: &JoysafeterClient) {
        for (group_id, credential_id) in self.created_members.drain(..).rev() {
            let _ = client
                .delete_credential_group_member(group_id, credential_id)
                .await;
        }
        for group_id in self.created_groups.drain(..).rev() {
            let _ = client.delete_credential_group(group_id).await;
        }
        self.credential_group_ids.clear();
    }

    pub async fn create_session_with_rollback(
        &mut self,
        client: &JoysafeterClient,
        body: &Value,
    ) -> anyhow::Result<Value> {
        let result = client.create_session(body).await;
        self.rollback_operation_on_error(client, result).await
    }

    async fn rollback_operation_on_error<T>(
        &mut self,
        client: &JoysafeterClient,
        result: anyhow::Result<T>,
    ) -> anyhow::Result<T> {
        if result.is_err() {
            self.rollback_created(client).await;
        }
        result
    }

    async fn cleanup_unselected_created(&mut self, client: &JoysafeterClient) {
        let selected: HashSet<CredentialGroupId> =
            self.credential_group_ids.iter().copied().collect();

        let mut retained_members = Vec::new();
        for (group_id, credential_id) in self.created_members.drain(..) {
            if selected.contains(&group_id) {
                retained_members.push((group_id, credential_id));
            } else {
                let _ = client
                    .delete_credential_group_member(group_id, credential_id)
                    .await;
            }
        }
        self.created_members = retained_members;

        let mut retained_groups = Vec::new();
        for group_id in self.created_groups.drain(..) {
            if selected.contains(&group_id) {
                retained_groups.push(group_id);
            } else {
                let _ = client.delete_credential_group(group_id).await;
            }
        }
        self.created_groups = retained_groups;
    }
}

pub fn normalize_mcp_server_url(raw: &str) -> String {
    let trimmed = raw.trim();
    let mut url = match Url::parse(trimmed) {
        Ok(url) if url.host_str().is_some() => url,
        _ => return trimmed.to_string(),
    };

    url.set_fragment(None);
    let path = url.path().to_string();
    let normalized_path = if path == "/" {
        ""
    } else if let Some(stripped) = path.strip_suffix('/') {
        stripped
    } else {
        &path
    };
    url.set_path(normalized_path);

    let serialized = url.to_string();
    if url.path().is_empty() || url.path() == "/" {
        if url.query().is_none() {
            return serialized
                .strip_suffix('/')
                .unwrap_or(&serialized)
                .to_string();
        }
        return serialized.replacen("/?", "?", 1);
    }
    serialized
}

pub fn parse_agent_endpoints(agent: &Value) -> anyhow::Result<Vec<McpEndpoint>> {
    let servers = agent
        .get("mcp_servers")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut endpoints = Vec::new();

    for server in servers {
        let transport = required_string(&server, "type", "MCP server")?;
        if transport == "local_stdio" {
            continue;
        }
        if transport != "streamable_http" && transport != "sse" {
            bail!("MCP server has unsupported transport '{}'", transport);
        }

        let name = required_string(&server, "name", "MCP server")?;
        let url = required_string(&server, "url", &format!("MCP server '{}'", name))?;
        let auth_requirement = match required_string(
            &server,
            "auth_requirement",
            &format!("MCP server '{}'", name),
        )?
        .as_str()
        {
            "required" => McpAuthRequirement::Required,
            "optional" => McpAuthRequirement::Optional,
            "none" => McpAuthRequirement::None,
            other => bail!(
                "MCP server '{}' has unsupported auth_requirement '{}'",
                name,
                other
            ),
        };
        if transport == "sse" && auth_requirement != McpAuthRequirement::None {
            bail!(
                "MCP server '{}' uses SSE, which only supports auth_requirement 'none'",
                name
            );
        }

        endpoints.push(McpEndpoint {
            name,
            normalized_url: normalize_mcp_server_url(&url),
            url,
            auth_requirement,
        });
    }

    Ok(endpoints)
}

pub fn parse_credential_group(group: &Value, members: &[Value]) -> anyhow::Result<CredentialGroup> {
    let id = required_string(group, "id", "credential group")?
        .parse::<CredentialGroupId>()
        .context("credential group response contained a non-canonical id")?;
    let name = required_string(group, "name", "credential group")?;
    let member_urls = members
        .iter()
        .filter(|member| member.get("archived_at").is_none_or(Value::is_null))
        .map(|member| {
            required_string(member, "mcp_server_url", "MCP credential")
                .map(|url| normalize_mcp_server_url(&url))
        })
        .collect::<anyhow::Result<Vec<_>>>()?;

    Ok(CredentialGroup {
        id,
        name,
        archived: group
            .get("archived_at")
            .is_some_and(|value| !value.is_null()),
        member_urls,
    })
}

pub fn evaluate_coverage(
    endpoints: &[McpEndpoint],
    groups: &[CredentialGroup],
    selected_group_ids: &[CredentialGroupId],
) -> CoverageSummary {
    let selected: HashSet<CredentialGroupId> = selected_group_ids.iter().copied().collect();
    let endpoints = endpoints
        .iter()
        .cloned()
        .map(|endpoint| {
            let matching_credential_count = groups
                .iter()
                .filter(|group| !group.archived && selected.contains(&group.id))
                .map(|group| {
                    group
                        .member_urls
                        .iter()
                        .filter(|url| *url == &endpoint.normalized_url)
                        .count()
                })
                .sum();
            let status = match endpoint.auth_requirement {
                McpAuthRequirement::None => CoverageStatus::NotRequired,
                McpAuthRequirement::Required if matching_credential_count == 0 => {
                    CoverageStatus::MissingRequired
                }
                McpAuthRequirement::Optional if matching_credential_count == 0 => {
                    CoverageStatus::OptionalAnonymous
                }
                _ if matching_credential_count == 1 => CoverageStatus::Matched,
                _ => CoverageStatus::Ambiguous,
            };
            EndpointCoverage {
                endpoint,
                matching_credential_count,
                status,
            }
        })
        .collect::<Vec<_>>();
    let blocking = endpoints.iter().any(|coverage| {
        matches!(
            coverage.status,
            CoverageStatus::MissingRequired | CoverageStatus::Ambiguous
        )
    });
    CoverageSummary {
        endpoints,
        blocking,
    }
}

pub fn validate_selected_groups(
    endpoints: &[McpEndpoint],
    groups: &[CredentialGroup],
    selected_group_ids: &[CredentialGroupId],
) -> anyhow::Result<CoverageSummary> {
    for group_id in selected_group_ids {
        let group = groups
            .iter()
            .find(|group| group.id == *group_id)
            .with_context(|| format!("credential group {} is not available", group_id))?;
        if group.archived {
            bail!("credential group {} ({}) is archived", group.name, group.id);
        }
    }

    let coverage = evaluate_coverage(endpoints, groups, selected_group_ids);
    let missing = coverage
        .endpoints
        .iter()
        .filter(|entry| entry.status == CoverageStatus::MissingRequired)
        .map(|entry| format!("{} ({})", entry.endpoint.name, entry.endpoint.url))
        .collect::<Vec<_>>();
    let ambiguous = coverage
        .endpoints
        .iter()
        .filter(|entry| entry.status == CoverageStatus::Ambiguous)
        .map(|entry| {
            format!(
                "{} ({}, {} matches)",
                entry.endpoint.name, entry.endpoint.url, entry.matching_credential_count
            )
        })
        .collect::<Vec<_>>();

    if !missing.is_empty() {
        bail!(
            "required MCP credentials are missing for {}. Select exactly one matching group with --credential-group <credgrp_...> or run interactively",
            missing.join(", ")
        );
    }
    if !ambiguous.is_empty() {
        bail!(
            "selected credential groups create ambiguous MCP credentials for {}. Remove groups until each endpoint has at most one match",
            ambiguous.join(", ")
        );
    }
    Ok(coverage)
}

pub fn build_mcp_credential_member_body(
    name: &str,
    mcp_server_url: &str,
    auth_scheme: &str,
    token_value: &str,
    header_name: Option<&str>,
    value_prefix: Option<&str>,
) -> anyhow::Result<Value> {
    let name = non_empty(name, "MCP credential name")?;
    let mcp_server_url = non_empty(mcp_server_url, "MCP server URL")?;
    let token_value = non_empty(token_value, "MCP credential value")?;
    let mut data =
        serde_json::Map::from_iter([("token_value".to_string(), Value::String(token_value))]);

    match auth_scheme {
        "static_bearer" => {}
        "header_api_key" => {
            data.insert(
                "header_name".to_string(),
                Value::String(non_empty(header_name.unwrap_or_default(), "Header name")?),
            );
        }
        "custom_header" => {
            data.insert(
                "header_name".to_string(),
                Value::String(non_empty(header_name.unwrap_or_default(), "Header name")?),
            );
            if let Some(value_prefix) = value_prefix.filter(|value| !value.is_empty()) {
                data.insert(
                    "value_prefix".to_string(),
                    Value::String(value_prefix.to_string()),
                );
            }
        }
        other => bail!("unsupported MCP authentication scheme '{}'", other),
    }

    Ok(serde_json::json!({
        "name": name,
        "mcp_server_url": mcp_server_url,
        "auth_scheme": auth_scheme,
        "data": data,
    }))
}

pub async fn authorize_session_interactively(
    client: &JoysafeterClient,
    agent: &Value,
    authorization: &mut SessionAuthorization,
) -> anyhow::Result<bool> {
    let result = authorize_session_interactively_inner(client, agent, authorization).await;
    authorization
        .rollback_operation_on_error(client, result)
        .await
}

async fn authorize_session_interactively_inner(
    client: &JoysafeterClient,
    agent: &Value,
    authorization: &mut SessionAuthorization,
) -> anyhow::Result<bool> {
    let endpoints = parse_agent_endpoints(agent)?;
    if !endpoints
        .iter()
        .any(|endpoint| endpoint.auth_requirement != McpAuthRequirement::None)
    {
        authorization.credential_group_ids.clear();
        authorization.cleanup_unselected_created(client).await;
        if endpoints.is_empty() {
            println!("  MCP authorization: no remote MCP endpoints declared; skipped.");
        } else {
            println!("  MCP authorization: all remote endpoints are public; no group is needed.");
        }
        return Ok(true);
    }

    let mut groups = load_credential_groups(client, &authorization.credential_group_ids).await?;
    loop {
        let coverage = evaluate_coverage(&endpoints, &groups, &authorization.credential_group_ids);
        print_coverage(&coverage, &groups, &authorization.credential_group_ids);

        let mut actions = Vec::new();
        if !coverage.blocking {
            actions.push("Continue with this authorization");
        }
        let has_matching_group = groups.iter().any(|group| {
            !group.archived
                && !authorization.credential_group_ids.contains(&group.id)
                && endpoints.iter().any(|endpoint| {
                    endpoint.auth_requirement != McpAuthRequirement::None
                        && group.member_urls.contains(&endpoint.normalized_url)
                })
        });
        if has_matching_group {
            actions.push("Add an existing credential group");
        }
        if !authorization.credential_group_ids.is_empty() {
            actions.push("Remove a selected credential group");
        }
        actions.push("Create a credential for an endpoint");
        actions.push("Cancel MCP authorization");

        let action = Select::new()
            .with_prompt("MCP authorization action")
            .items(&actions)
            .default(0)
            .interact()?;
        match actions[action] {
            "Continue with this authorization" => {
                validate_selected_groups(&endpoints, &groups, &authorization.credential_group_ids)?;
                authorization.cleanup_unselected_created(client).await;
                return Ok(true);
            }
            "Add an existing credential group" => {
                add_existing_group(&endpoints, &groups, &mut authorization.credential_group_ids)?;
            }
            "Remove a selected credential group" => {
                remove_selected_group(&groups, &mut authorization.credential_group_ids)?;
            }
            "Create a credential for an endpoint" => {
                create_endpoint_credential(client, agent, &coverage, &mut groups, authorization)
                    .await?;
            }
            "Cancel MCP authorization" => {
                authorization.rollback_created(client).await;
                return Ok(false);
            }
            _ => unreachable!(),
        }
    }
}

pub async fn validate_session_authorization(
    client: &JoysafeterClient,
    agent: &Value,
    authorization: &mut SessionAuthorization,
) -> anyhow::Result<()> {
    let endpoints = parse_agent_endpoints(agent)?;
    if !endpoints
        .iter()
        .any(|endpoint| endpoint.auth_requirement != McpAuthRequirement::None)
    {
        authorization.credential_group_ids.clear();
        return Ok(());
    }
    let groups = load_credential_groups(client, &authorization.credential_group_ids).await?;
    validate_selected_groups(&endpoints, &groups, &authorization.credential_group_ids)?;
    Ok(())
}

pub async fn create_credential_group_member_interactively(
    client: &JoysafeterClient,
    group_id: CredentialGroupId,
    default_name: Option<&str>,
    default_url: Option<&str>,
) -> anyhow::Result<Value> {
    let body = prompt_credential_body(default_name, default_url)?;
    client.create_credential_group_member(group_id, &body).await
}

pub fn build_session_body(
    agent_id: AgentId,
    environment_id: Option<EnvironmentId>,
    title: Option<&str>,
    resources: &[Value],
    credential_group_ids: &[CredentialGroupId],
) -> Value {
    let mut unique_group_ids = Vec::new();
    let mut seen_group_ids = HashSet::new();
    for group_id in credential_group_ids {
        if seen_group_ids.insert(*group_id) {
            unique_group_ids.push(*group_id);
        }
    }

    let mut body = serde_json::json!({
        "agent_id": agent_id,
        "credential_group_ids": unique_group_ids,
    });
    if let Some(environment_id) = environment_id {
        body["environment_id"] = serde_json::json!(environment_id);
    }
    if let Some(title) = title.map(str::trim).filter(|value| !value.is_empty()) {
        body["title"] = Value::String(title.to_string());
    }
    if !resources.is_empty() {
        body["resources"] = serde_json::json!(resources);
    }
    body
}

fn required_string(value: &Value, field: &str, context: &str) -> anyhow::Result<String> {
    let value = value
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .with_context(|| format!("{} response missing {}", context, field))?;
    Ok(value.to_string())
}

fn non_empty(value: &str, field: &str) -> anyhow::Result<String> {
    let value = value.trim();
    if value.is_empty() {
        bail!("{} cannot be empty", field);
    }
    Ok(value.to_string())
}

fn deduplicate_group_ids(group_ids: &[CredentialGroupId]) -> Vec<CredentialGroupId> {
    let mut seen = HashSet::new();
    group_ids
        .iter()
        .copied()
        .filter(|group_id| seen.insert(*group_id))
        .collect()
}

async fn load_credential_groups(
    client: &JoysafeterClient,
    selected_group_ids: &[CredentialGroupId],
) -> anyhow::Result<Vec<CredentialGroup>> {
    let selected: HashSet<CredentialGroupId> = selected_group_ids.iter().copied().collect();
    let mut raw_groups = client
        .list_credential_groups()
        .await
        .context("failed to load MCP credential groups")?;
    for group_id in selected_group_ids {
        let already_loaded = raw_groups
            .iter()
            .any(|group| group.get("id").and_then(Value::as_str) == Some(&group_id.to_string()));
        if !already_loaded {
            raw_groups.push(
                client
                    .get_credential_group(*group_id)
                    .await
                    .with_context(|| format!("failed to load credential group {}", group_id))?,
            );
        }
    }

    let mut groups = Vec::with_capacity(raw_groups.len());
    for raw_group in raw_groups {
        let group_id = match required_string(&raw_group, "id", "credential group")?
            .parse::<CredentialGroupId>()
        {
            Ok(group_id) => group_id,
            Err(error) => {
                eprintln!(
                    "  Warning: ignoring malformed credential group id: {}",
                    error
                );
                continue;
            }
        };
        let members = match client.list_credential_group_members(group_id).await {
            Ok(members) => members,
            Err(error) if !selected.contains(&group_id) => {
                eprintln!(
                    "  Warning: credential group {} is unavailable and will not be offered: {}",
                    group_id, error
                );
                continue;
            }
            Err(error) => {
                return Err(error).with_context(|| {
                    format!("failed to load selected credential group {}", group_id)
                });
            }
        };
        match parse_credential_group(&raw_group, &members) {
            Ok(group) => groups.push(group),
            Err(error) if !selected.contains(&group_id) => {
                eprintln!(
                    "  Warning: credential group {} has an invalid response and will not be offered: {}",
                    group_id, error
                );
            }
            Err(error) => {
                return Err(error).with_context(|| {
                    format!(
                        "selected credential group {} has an invalid response",
                        group_id
                    )
                });
            }
        }
    }
    Ok(groups)
}

fn print_coverage(
    coverage: &CoverageSummary,
    groups: &[CredentialGroup],
    selected_group_ids: &[CredentialGroupId],
) {
    println!("\n── MCP Authorization ──");
    if selected_group_ids.is_empty() {
        println!("  Selected groups: none");
    } else {
        let labels = selected_group_ids
            .iter()
            .map(|group_id| {
                groups
                    .iter()
                    .find(|group| group.id == *group_id)
                    .map(|group| format!("{} ({})", group.name, group.id))
                    .unwrap_or_else(|| group_id.to_string())
            })
            .collect::<Vec<_>>();
        println!("  Selected groups: {}", labels.join(", "));
    }
    for entry in &coverage.endpoints {
        let (symbol, message) = match entry.status {
            CoverageStatus::Matched => ("✓", "one matching credential".to_string()),
            CoverageStatus::OptionalAnonymous => ("○", "anonymous by default".to_string()),
            CoverageStatus::NotRequired => ("–", "managed credentials ignored".to_string()),
            CoverageStatus::MissingRequired => ("!", "required credential missing".to_string()),
            CoverageStatus::Ambiguous => (
                "!",
                format!(
                    "{} matching credentials; select exactly one",
                    entry.matching_credential_count
                ),
            ),
        };
        println!(
            "  {} {} [{}] {}",
            symbol, entry.endpoint.name, entry.endpoint.url, message
        );
    }
}

fn add_existing_group(
    endpoints: &[McpEndpoint],
    groups: &[CredentialGroup],
    selected_group_ids: &mut Vec<CredentialGroupId>,
) -> anyhow::Result<()> {
    let candidates = groups
        .iter()
        .filter(|group| !group.archived && !selected_group_ids.contains(&group.id))
        .filter_map(|group| {
            let endpoint_names = endpoints
                .iter()
                .filter(|endpoint| endpoint.auth_requirement != McpAuthRequirement::None)
                .filter(|endpoint| group.member_urls.contains(&endpoint.normalized_url))
                .map(|endpoint| endpoint.name.as_str())
                .collect::<Vec<_>>();
            (!endpoint_names.is_empty()).then_some((group, endpoint_names))
        })
        .collect::<Vec<_>>();
    if candidates.is_empty() {
        println!("  No unselected credential group matches this Agent's MCP endpoints.");
        return Ok(());
    }

    let labels = candidates
        .iter()
        .map(|(group, endpoints)| {
            format!(
                "{} ({}) — covers {}",
                group.name,
                group.id,
                endpoints.join(", ")
            )
        })
        .collect::<Vec<_>>();
    let index = Select::new()
        .with_prompt("Select credential group")
        .items(&labels)
        .default(0)
        .interact()?;
    selected_group_ids.push(candidates[index].0.id);
    Ok(())
}

fn remove_selected_group(
    groups: &[CredentialGroup],
    selected_group_ids: &mut Vec<CredentialGroupId>,
) -> anyhow::Result<()> {
    let labels = selected_group_ids
        .iter()
        .map(|group_id| {
            groups
                .iter()
                .find(|group| group.id == *group_id)
                .map(|group| format!("{} ({})", group.name, group.id))
                .unwrap_or_else(|| group_id.to_string())
        })
        .collect::<Vec<_>>();
    let index = Select::new()
        .with_prompt("Remove credential group")
        .items(&labels)
        .default(0)
        .interact()?;
    selected_group_ids.remove(index);
    Ok(())
}

async fn create_endpoint_credential(
    client: &JoysafeterClient,
    agent: &Value,
    coverage: &CoverageSummary,
    groups: &mut Vec<CredentialGroup>,
    authorization: &mut SessionAuthorization,
) -> anyhow::Result<()> {
    let candidates = coverage
        .endpoints
        .iter()
        .filter(|entry| {
            matches!(
                entry.status,
                CoverageStatus::MissingRequired | CoverageStatus::OptionalAnonymous
            )
        })
        .collect::<Vec<_>>();
    if candidates.is_empty() {
        println!("  No endpoint needs a new credential. Resolve ambiguity by removing a group.");
        return Ok(());
    }
    let labels = candidates
        .iter()
        .map(|entry| {
            let requirement = match entry.endpoint.auth_requirement {
                McpAuthRequirement::Required => "required",
                McpAuthRequirement::Optional => "optional",
                McpAuthRequirement::None => "none",
            };
            format!(
                "{} ({}) — {}",
                entry.endpoint.name, entry.endpoint.url, requirement
            )
        })
        .collect::<Vec<_>>();
    let endpoint_index = Select::new()
        .with_prompt("Create credential for endpoint")
        .items(&labels)
        .default(0)
        .interact()?;
    let endpoint = &candidates[endpoint_index].endpoint;

    let eligible_groups = groups
        .iter()
        .filter(|group| !group.archived && !group.member_urls.contains(&endpoint.normalized_url))
        .collect::<Vec<_>>();
    let mut group_labels = eligible_groups
        .iter()
        .map(|group| format!("{} ({})", group.name, group.id))
        .collect::<Vec<_>>();
    group_labels.push("+ Create a new credential group".to_string());
    let group_index = Select::new()
        .with_prompt("Store credential in")
        .items(&group_labels)
        .default(0)
        .interact()?;
    let group_id = if group_index == eligible_groups.len() {
        let agent_name = agent.get("name").and_then(Value::as_str).unwrap_or("Agent");
        let default_group_name = format!("{} MCP", agent_name);
        let group_name: String = Input::new()
            .with_prompt("Credential group name")
            .default(default_group_name)
            .interact_text()?;
        let body = prompt_credential_body(Some(&endpoint.name), Some(&endpoint.url))?;
        let group_response = client
            .create_credential_group(&serde_json::json!({
                "name": non_empty(&group_name, "Credential group name")?,
                "description": format!("MCP credentials authorized per Session for {}", agent_name),
                "initial_members": [body],
            }))
            .await?;
        let group_id = required_string(&group_response, "id", "credential group")?
            .parse::<CredentialGroupId>()
            .context("credential group response contained a non-canonical id")?;
        authorization.created_groups.push(group_id);
        let members = client.list_credential_group_members(group_id).await?;
        groups.push(parse_credential_group(&group_response, &members)?);
        group_id
    } else {
        let group_id = eligible_groups[group_index].id;
        let body = prompt_credential_body(Some(&endpoint.name), Some(&endpoint.url))?;
        let credential_response = client
            .create_credential_group_member(group_id, &body)
            .await?;
        let credential_id = required_string(&credential_response, "id", "MCP credential")?
            .parse::<CredentialId>()
            .context("MCP credential response contained a non-canonical id")?;
        let group = groups
            .iter_mut()
            .find(|group| group.id == group_id)
            .context("created MCP credential group disappeared from local catalog")?;
        group.member_urls.push(endpoint.normalized_url.clone());
        authorization
            .created_members
            .push((group_id, credential_id));
        group_id
    };
    if !authorization.credential_group_ids.contains(&group_id) {
        authorization.credential_group_ids.push(group_id);
    }
    Ok(())
}

fn prompt_credential_body(
    default_name: Option<&str>,
    default_url: Option<&str>,
) -> anyhow::Result<Value> {
    let mut name_prompt = Input::<String>::new().with_prompt("Credential name");
    if let Some(default_name) = default_name {
        name_prompt = name_prompt.default(default_name.to_string());
    }
    let name = non_empty(&name_prompt.interact_text()?, "Credential name")?;

    let mut url_prompt =
        Input::<String>::new().with_prompt("MCP server URL (must match Agent URL)");
    if let Some(default_url) = default_url {
        url_prompt = url_prompt.default(default_url.to_string());
    }
    let url = non_empty(&url_prompt.interact_text()?, "MCP server URL")?;

    let schemes = [
        "Bearer token (Authorization: Bearer …)",
        "API key header",
        "Custom header",
    ];
    let scheme_index = Select::new()
        .with_prompt("Authentication scheme")
        .items(&schemes)
        .default(0)
        .interact()?;
    let auth_scheme = ["static_bearer", "header_api_key", "custom_header"][scheme_index];
    let header_name = match auth_scheme {
        "header_api_key" => Some(
            Input::<String>::new()
                .with_prompt("Header name")
                .default("X-Api-Key".to_string())
                .interact_text()?,
        ),
        "custom_header" => Some(
            Input::<String>::new()
                .with_prompt("Header name")
                .interact_text()?,
        ),
        _ => None,
    };
    let value_prefix = if auth_scheme == "custom_header" {
        Some(
            Input::<String>::new()
                .with_prompt("Value prefix (optional, e.g. Token )")
                .allow_empty(true)
                .interact_text()?,
        )
    } else {
        None
    };
    let token_value = Password::new()
        .with_prompt("Credential secret")
        .interact()?;

    build_mcp_credential_member_body(
        &name,
        &url,
        auth_scheme,
        &token_value,
        header_name.as_deref(),
        value_prefix.as_deref(),
    )
}

#[cfg(test)]
mod tests {
    use super::{
        build_mcp_credential_member_body, build_session_body, evaluate_coverage,
        normalize_mcp_server_url, parse_agent_endpoints, parse_credential_group,
        validate_selected_groups, CoverageStatus, SessionAuthorization,
    };
    use crate::client::JoysafeterClient;
    use joysafeter_entity_id::{AgentId, CredentialGroupId, EnvironmentId};
    use serde::Deserialize;
    use serde_json::json;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::path::PathBuf;
    use std::sync::mpsc;

    #[derive(Deserialize)]
    struct UrlVector {
        raw: String,
        normalized: String,
    }

    #[test]
    fn normalizes_urls_using_the_shared_contract() {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../../../backend/tests/fixtures/mcp_url_vectors.json");
        let vectors: Vec<UrlVector> =
            serde_json::from_str(&std::fs::read_to_string(path).expect("read MCP URL vectors"))
                .expect("parse MCP URL vectors");

        for vector in vectors {
            assert_eq!(normalize_mcp_server_url(&vector.raw), vector.normalized);
        }
        assert_eq!(
            normalize_mcp_server_url("https://example.com/api//"),
            "https://example.com/api/"
        );
    }

    #[test]
    fn evaluates_only_agent_declared_remote_endpoints() {
        let agent = json!({
            "mcp_servers": [
                {
                    "type": "streamable_http",
                    "name": "required-api",
                    "url": "https://required.example.com/mcp/",
                    "auth_requirement": "required"
                },
                {
                    "type": "streamable_http",
                    "name": "optional-api",
                    "url": "https://optional.example.com/mcp",
                    "auth_requirement": "optional"
                },
                {
                    "type": "streamable_http",
                    "name": "public-api",
                    "url": "https://public.example.com/mcp",
                    "auth_requirement": "none"
                },
                {
                    "type": "local_stdio",
                    "name": "local",
                    "command": "node",
                    "args": []
                }
            ]
        });
        let endpoints = parse_agent_endpoints(&agent).unwrap();

        let required_group_id = CredentialGroupId::new();
        let duplicate_group_id = CredentialGroupId::new();
        let unrelated_group_id = CredentialGroupId::new();
        let groups = vec![
            parse_credential_group(
                &json!({"id": required_group_id, "name": "required"}),
                &[json!({
                    "mcp_server_url": "HTTPS://REQUIRED.EXAMPLE.COM:443/mcp",
                    "archived_at": null
                })],
            )
            .unwrap(),
            parse_credential_group(
                &json!({"id": duplicate_group_id, "name": "duplicate"}),
                &[
                    json!({"mcp_server_url": "https://optional.example.com/mcp"}),
                    json!({"mcp_server_url": "https://public.example.com/mcp"}),
                ],
            )
            .unwrap(),
            parse_credential_group(
                &json!({"id": unrelated_group_id, "name": "unrelated"}),
                &[
                    json!({"mcp_server_url": "https://unrelated.example.com/mcp"}),
                    json!({"mcp_server_url": "https://unrelated.example.com/mcp"}),
                ],
            )
            .unwrap(),
        ];

        let initial = evaluate_coverage(&endpoints, &groups, &[]);
        assert_eq!(initial.endpoints[0].status, CoverageStatus::MissingRequired);
        assert_eq!(
            initial.endpoints[1].status,
            CoverageStatus::OptionalAnonymous
        );
        assert_eq!(initial.endpoints[2].status, CoverageStatus::NotRequired);
        assert!(initial.blocking);

        let covered = evaluate_coverage(
            &endpoints,
            &groups,
            &[required_group_id, duplicate_group_id, unrelated_group_id],
        );
        assert_eq!(covered.endpoints[0].status, CoverageStatus::Matched);
        assert_eq!(covered.endpoints[1].status, CoverageStatus::Matched);
        assert_eq!(covered.endpoints[2].status, CoverageStatus::NotRequired);
        assert!(!covered.blocking);
    }

    #[test]
    fn detects_relevant_duplicates_but_ignores_archived_members() {
        let endpoint = parse_agent_endpoints(&json!({
            "mcp_servers": [{
                "type": "streamable_http",
                "name": "api",
                "url": "https://example.com/mcp",
                "auth_requirement": "optional"
            }]
        }))
        .unwrap();
        let first_id = CredentialGroupId::new();
        let second_id = CredentialGroupId::new();
        let first = parse_credential_group(
            &json!({"id": first_id, "name": "first"}),
            &[json!({"mcp_server_url": "https://example.com/mcp"})],
        )
        .unwrap();
        let second = parse_credential_group(
            &json!({"id": second_id, "name": "second"}),
            &[
                json!({"mcp_server_url": "https://example.com/mcp/"}),
                json!({
                    "mcp_server_url": "https://example.com/mcp",
                    "archived_at": "2026-08-25T00:00:00Z"
                }),
            ],
        )
        .unwrap();

        let coverage = evaluate_coverage(&endpoint, &[first, second], &[first_id, second_id]);
        assert_eq!(coverage.endpoints[0].status, CoverageStatus::Ambiguous);
        assert_eq!(coverage.endpoints[0].matching_credential_count, 2);
        assert!(coverage.blocking);
    }

    #[test]
    fn rejects_invalid_agent_mcp_contracts() {
        let missing_requirement = json!({
            "mcp_servers": [{
                "type": "streamable_http",
                "name": "api",
                "url": "https://example.com/mcp"
            }]
        });
        assert!(parse_agent_endpoints(&missing_requirement).is_err());

        let authenticated_sse = json!({
            "mcp_servers": [{
                "type": "sse",
                "name": "events",
                "url": "https://example.com/sse",
                "auth_requirement": "required"
            }]
        });
        assert!(parse_agent_endpoints(&authenticated_sse).is_err());
    }

    #[test]
    fn builds_one_canonical_session_payload() {
        let agent_id = AgentId::new();
        let environment_id = EnvironmentId::new();
        let first_group_id = CredentialGroupId::new();
        let second_group_id = CredentialGroupId::new();

        let body = build_session_body(
            agent_id,
            Some(environment_id),
            Some("  Production session  "),
            &[json!({"type": "session_memory_store", "memory_store_id": "memstore_test"})],
            &[first_group_id, first_group_id, second_group_id],
        );

        assert_eq!(body["agent_id"], json!(agent_id));
        assert_eq!(body["environment_id"], json!(environment_id));
        assert_eq!(body["title"], "Production session");
        assert_eq!(
            body["credential_group_ids"],
            json!([first_group_id, second_group_id])
        );
        assert_eq!(body["resources"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn rejects_unknown_or_archived_explicit_groups() {
        let endpoints = parse_agent_endpoints(&json!({
            "mcp_servers": [{
                "type": "streamable_http",
                "name": "api",
                "url": "https://example.com/mcp",
                "auth_requirement": "optional"
            }]
        }))
        .unwrap();
        let archived_id = CredentialGroupId::new();
        let archived = parse_credential_group(
            &json!({
                "id": archived_id,
                "name": "archived",
                "archived_at": "2026-08-25T00:00:00Z"
            }),
            &[],
        )
        .unwrap();

        let unknown_error = validate_selected_groups(
            &endpoints,
            std::slice::from_ref(&archived),
            &[CredentialGroupId::new()],
        )
        .unwrap_err()
        .to_string();
        assert!(unknown_error.contains("not available"));

        let archived_error = validate_selected_groups(&endpoints, &[archived], &[archived_id])
            .unwrap_err()
            .to_string();
        assert!(archived_error.contains("archived"));
    }

    #[test]
    fn blocking_errors_name_the_endpoint_and_recovery_action() {
        let endpoints = parse_agent_endpoints(&json!({
            "mcp_servers": [{
                "type": "streamable_http",
                "name": "private-search",
                "url": "https://search.example.com/mcp",
                "auth_requirement": "required"
            }]
        }))
        .unwrap();

        let error = validate_selected_groups(&endpoints, &[], &[])
            .unwrap_err()
            .to_string();
        assert!(error.contains("private-search"));
        assert!(error.contains("--credential-group"));
    }

    #[test]
    fn builds_scheme_specific_credential_material() {
        assert_eq!(
            build_mcp_credential_member_body(
                "Bearer",
                "https://example.com/mcp",
                "static_bearer",
                "secret",
                None,
                None,
            )
            .unwrap()["data"],
            json!({"token_value": "secret"})
        );
        assert_eq!(
            build_mcp_credential_member_body(
                "API key",
                "https://example.com/mcp",
                "header_api_key",
                "secret",
                Some("X-Api-Key"),
                None,
            )
            .unwrap()["data"],
            json!({"token_value": "secret", "header_name": "X-Api-Key"})
        );
        assert_eq!(
            build_mcp_credential_member_body(
                "Custom",
                "https://example.com/mcp",
                "custom_header",
                "secret",
                Some("X-Service-Authorization"),
                Some("Token "),
            )
            .unwrap()["data"],
            json!({
                "token_value": "secret",
                "header_name": "X-Service-Authorization",
                "value_prefix": "Token "
            })
        );
    }

    #[tokio::test]
    async fn session_creation_failure_rolls_back_inline_created_groups() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let (request_tx, request_rx) = mpsc::channel();
        let server = std::thread::spawn(move || {
            for (status, body) in [
                (
                    "500 Internal Server Error",
                    r#"{"error":"session rejected"}"#,
                ),
                ("200 OK", "{}"),
            ] {
                let (mut stream, _) = listener.accept().unwrap();
                let mut request = [0_u8; 4096];
                let bytes_read = stream.read(&mut request).unwrap();
                let request = String::from_utf8_lossy(&request[..bytes_read]);
                request_tx
                    .send(request.lines().next().unwrap_or_default().to_string())
                    .unwrap();
                write!(
                    stream,
                    "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                )
                .unwrap();
            }
        });

        let group_id = CredentialGroupId::new();
        let mut authorization = SessionAuthorization {
            credential_group_ids: vec![group_id],
            created_groups: vec![group_id],
            created_members: Vec::new(),
        };
        let client = JoysafeterClient::new(&format!("http://{address}"), None);

        let error = authorization
            .create_session_with_rollback(&client, &json!({"agent_id": AgentId::new()}))
            .await
            .unwrap_err()
            .to_string();

        assert!(error.contains("POST /sessions failed"));
        assert_eq!(request_rx.recv().unwrap(), "POST /api/v1/sessions HTTP/1.1");
        assert_eq!(
            request_rx.recv().unwrap(),
            format!("DELETE /api/v1/credential-groups/{group_id} HTTP/1.1")
        );
        assert!(authorization.credential_group_ids.is_empty());
        assert!(authorization.created_groups.is_empty());
        server.join().unwrap();
    }

    #[tokio::test]
    async fn authorization_operation_failure_rolls_back_inline_created_groups() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let (request_tx, request_rx) = mpsc::channel();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut request = [0_u8; 4096];
            let bytes_read = stream.read(&mut request).unwrap();
            let request = String::from_utf8_lossy(&request[..bytes_read]);
            request_tx
                .send(request.lines().next().unwrap_or_default().to_string())
                .unwrap();
            let body = "{}";
            write!(
                stream,
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            )
            .unwrap();
        });

        let group_id = CredentialGroupId::new();
        let mut authorization = SessionAuthorization {
            credential_group_ids: vec![group_id],
            created_groups: vec![group_id],
            created_members: Vec::new(),
        };
        let client = JoysafeterClient::new(&format!("http://{address}"), None);

        let error = authorization
            .rollback_operation_on_error::<()>(
                &client,
                Err(anyhow::anyhow!("credential member refresh failed")),
            )
            .await
            .unwrap_err()
            .to_string();

        assert_eq!(error, "credential member refresh failed");
        assert_eq!(
            request_rx.recv().unwrap(),
            format!("DELETE /api/v1/credential-groups/{group_id} HTTP/1.1")
        );
        assert!(authorization.credential_group_ids.is_empty());
        assert!(authorization.created_groups.is_empty());
        server.join().unwrap();
    }
}
