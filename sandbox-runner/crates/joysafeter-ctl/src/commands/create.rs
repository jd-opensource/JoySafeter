use crate::client::JoysafeterClient;
use crate::editor::open_in_editor;
use crate::CreateResource;
use anyhow::{bail, Context};
use dialoguer::{Confirm, Input, Select};
use joysafeter_entity_id::{AgentId, CredentialGroupId, EnvironmentId, MemoryStoreId, SessionId};

use super::mcp_authorization::{
    authorize_session_interactively, build_session_body,
    create_credential_group_member_interactively, SessionAuthorization,
};

pub async fn run(client: &JoysafeterClient, resource: &CreateResource) -> anyhow::Result<()> {
    match resource {
        CreateResource::Credential => create_credential(client).await,
        CreateResource::Environment => create_environment(client).await,
        CreateResource::Agent => create_agent(client).await,
        CreateResource::Session => create_session(client).await,
        CreateResource::Event => send_event(client).await,
        CreateResource::MemoryStore => create_memory_store(client).await,
        CreateResource::Memory => create_memory(client).await,
        CreateResource::CredentialGroup => create_credential_group(client).await,
        CreateResource::CredentialGroupMember => create_credential_group_member(client).await,
    }
}

fn input_required(prompt: &str) -> anyhow::Result<String> {
    let val: String = Input::new().with_prompt(prompt).interact_text()?;
    if val.trim().is_empty() {
        bail!("{} cannot be empty", prompt);
    }
    Ok(val.trim().to_string())
}

fn input_optional(prompt: &str) -> anyhow::Result<Option<String>> {
    let val: String = Input::new()
        .with_prompt(prompt)
        .allow_empty(true)
        .interact_text()?;
    if val.trim().is_empty() {
        Ok(None)
    } else {
        Ok(Some(val.trim().to_string()))
    }
}

fn select_from_list(
    items: &[serde_json::Value],
    name_field: &str,
    prompt: &str,
    allow_none: bool,
) -> anyhow::Result<Option<usize>> {
    let mut labels: Vec<String> = Vec::new();
    if allow_none {
        labels.push("(none)".to_string());
    }
    for item in items {
        labels.push(item[name_field].as_str().unwrap_or("?").to_string());
    }

    let idx = Select::new()
        .with_prompt(prompt)
        .items(&labels)
        .default(0)
        .interact()?;

    if allow_none {
        if idx == 0 {
            Ok(None)
        } else {
            Ok(Some(idx - 1))
        }
    } else {
        Ok(Some(idx))
    }
}

// ── Credential ────────────────────────────────────────

async fn create_credential(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Credential ──\n");

    let kinds = ["model", "service"];
    let kind = kinds[Select::new()
        .with_prompt("Credential kind")
        .items(&kinds)
        .default(0)
        .interact()?];
    let name = input_required("Credential name")?;

    let mut data = serde_json::Map::new();
    loop {
        let key = input_required("Key name (e.g. ANTHROPIC_API_KEY, OPENAI_API_KEY)")?;
        let val: String = Input::new()
            .with_prompt(format!("Value for {}", key))
            .interact_text()?;
        data.insert(key, serde_json::Value::String(val));

        if !Confirm::new()
            .with_prompt("Add another key-value pair?")
            .default(false)
            .interact()?
        {
            break;
        }
    }

    if data.is_empty() {
        bail!("Credential must have at least one key-value pair");
    }

    let keys: Vec<&String> = data.keys().collect();
    println!("\n── Summary ──");
    println!("  Kind: {}", kind);
    println!("  Name: {}", name);
    println!(
        "  Keys: {}",
        keys.iter()
            .map(|k| k.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    );

    if !Confirm::new()
        .with_prompt("Create this credential?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let mut body = serde_json::json!({
        "kind": kind,
        "name": name,
        "data": serde_json::Value::Object(data),
    });
    if kind == "model" {
        body["provider"] = serde_json::Value::String(input_required("Provider")?);
        body["protocol"] = serde_json::Value::String(input_required("Protocol")?);
        body["is_default"] = serde_json::Value::Bool(
            Confirm::new()
                .with_prompt("Set as default model credential?")
                .default(false)
                .interact()?,
        );
    }
    let response = client.create_credential(&body).await?;
    println!(
        "\ncredential/{} created",
        response["id"].as_str().unwrap_or("?")
    );
    Ok(())
}

// ── Environment ───────────────────────────────────────

async fn create_environment(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Environment ──\n");

    let name = input_required("Environment name")?;

    let network_types = vec!["unrestricted", "limited"];
    let net_idx = Select::new()
        .with_prompt("Networking type")
        .items(&network_types)
        .default(0)
        .interact()?;
    let network_type = network_types[net_idx];

    let mut allowed_hosts: Vec<String> = Vec::new();
    if network_type == "limited" {
        while let Some(host) = input_optional("Allowed host (Enter to finish)")? {
            allowed_hosts.push(host);
        }
    }

    println!("\n── Summary ──");
    println!("  Name:       {}", name);
    println!("  Networking: {}", network_type);
    if !allowed_hosts.is_empty() {
        println!("  Hosts:      {}", allowed_hosts.join(", "));
    }

    if !Confirm::new()
        .with_prompt("Create this environment?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let mut networking = serde_json::json!({"type": network_type});
    if !allowed_hosts.is_empty() {
        networking["allowed_hosts"] = serde_json::json!(allowed_hosts);
    }

    let body = serde_json::json!({
        "name": name,
        "config": {
            "type": "cloud",
            "networking": networking,
        },
    });
    client.create_environment(&body).await?;
    println!("\nenvironment/{} created", name);
    Ok(())
}

// ── Agent ─────────────────────────────────────────────

async fn create_agent(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Agent ──\n");

    let name = input_required("Agent name")?;

    let engines = vec!["claude", "codex", "native"];
    let engine_idx = Select::new()
        .with_prompt("Engine")
        .items(&engines)
        .default(0)
        .interact()?;
    let engine = engines[engine_idx];

    let model = input_required("Model (e.g. Claude-Sonnet-4.6)")?;
    let description = input_optional("Description (optional)")?;

    let system_prompt = {
        let editor_result = open_in_editor(
            "# Enter system prompt (save and close to continue)\n",
            "system-prompt.md",
        );
        match editor_result {
            Ok(text) => {
                let trimmed = text.trim().to_string();
                if trimmed.is_empty() || trimmed.starts_with('#') {
                    input_optional("System prompt (optional)")?
                } else {
                    Some(trimmed)
                }
            }
            _ => input_optional("System prompt (optional)")?,
        }
    };

    let model_credential_id = {
        let credentials = client.list_credentials().await.unwrap_or_default();
        let model_credentials = credentials
            .into_iter()
            .filter(|credential| credential["kind"].as_str() == Some("model"))
            .collect::<Vec<_>>();
        if model_credentials.is_empty() {
            println!("  (No model credentials found, skipping model_credential_id)");
            None
        } else {
            match select_from_list(&model_credentials, "name", "Model credential", true)? {
                Some(idx) => model_credentials[idx]["id"].as_str().map(str::to_string),
                None => None,
            }
        }
    };

    let environment_id = {
        let envs = client.list_environments().await.unwrap_or_default();
        if envs.is_empty() {
            println!("  (No environments found, skipping environment_id)");
            None
        } else {
            match select_from_list(&envs, "name", "Environment", true)? {
                Some(idx) => Some(
                    envs[idx]["id"]
                        .as_str()
                        .context("environment response missing id")?
                        .parse::<EnvironmentId>()
                        .context("environment response contained a non-canonical id")?,
                ),
                None => None,
            }
        }
    };

    let policies = vec!["always_allow", "always_ask"];
    let policy_idx = Select::new()
        .with_prompt("Tool permission policy")
        .items(&policies)
        .default(0)
        .interact()?;
    let policy = policies[policy_idx];

    let mcp_servers = collect_mcp_servers()?;
    let custom_tools = collect_custom_tools()?;

    println!("\n── Summary ──");
    println!("  Name:          {}", name);
    println!("  Engine:        {}", engine);
    println!("  Model:         {}", model);
    println!("  Description:   {}", description.as_deref().unwrap_or("-"));
    if let Some(ref sp) = system_prompt {
        let preview: String = sp.chars().take(80).collect();
        println!("  System Prompt: {}...", preview);
    } else {
        println!("  System Prompt: -");
    }
    println!(
        "  Model Credential ID: {}",
        model_credential_id.as_deref().unwrap_or("-")
    );
    println!(
        "  Environment:   {}",
        environment_id
            .map(|id| id.to_string())
            .as_deref()
            .unwrap_or("-")
    );
    println!("  Tool Policy:   {}", policy);
    if !mcp_servers.is_empty() {
        println!("  MCP Servers:   {}", mcp_servers.len());
        for s in &mcp_servers {
            println!(
                "    - {} ({})",
                s["name"].as_str().unwrap_or("?"),
                s["type"].as_str().unwrap_or("?")
            );
        }
    }
    if !custom_tools.is_empty() {
        println!("  Custom Tools:  {}", custom_tools.len());
        for t in &custom_tools {
            println!("    - {}", t["name"].as_str().unwrap_or("?"));
        }
    }

    if !Confirm::new()
        .with_prompt("Create this agent?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let mut body = serde_json::json!({
        "name": name,
        "engine_kind": engine,
        "model": model,
        "tools": [{
            "type": "agent_toolset_20260401",
            "default_config": {
                "permission_policy": { "type": policy }
            }
        }],
    });
    if let Some(desc) = description {
        body["description"] = serde_json::Value::String(desc);
    }
    if let Some(sp) = system_prompt {
        body["system"] = serde_json::Value::String(sp);
    }
    if let Some(credential_id) = model_credential_id {
        body["model_credential_id"] = serde_json::Value::String(credential_id);
    }
    if let Some(environment_id) = environment_id {
        body["environment_id"] = serde_json::json!(environment_id);
    }
    if !mcp_servers.is_empty() {
        body["mcp_servers"] = serde_json::json!(mcp_servers);
        let tools = body["tools"].as_array_mut().unwrap();
        for s in &mcp_servers {
            let server_name = s["name"].as_str().unwrap();
            tools.push(serde_json::json!({
                "type": "mcp_toolset",
                "mcp_server_name": server_name
            }));
        }
    }
    if !custom_tools.is_empty() {
        let tools = body["tools"].as_array_mut().unwrap();
        for t in &custom_tools {
            tools.push(t.clone());
        }
    }

    client.create_agent(&body).await?;
    println!("\nagent/{} created", name);
    Ok(())
}

// ── Session ───────────────────────────────────────────

async fn create_session(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Session ──\n");

    let agents = client.list_agents().await?;
    if agents.is_empty() {
        bail!("No agents found. Create an agent first: joysafeterctl create agent");
    }
    let agent_idx = select_from_list(&agents, "name", "Select agent", false)?
        .expect("agent selection required");
    let agent_id = agents[agent_idx]["id"]
        .as_str()
        .context("agent response missing id")?
        .parse::<AgentId>()
        .context("agent response contained a non-canonical id")?;
    let agent_name = agents[agent_idx]["name"].as_str().unwrap_or("?");

    let envs = client.list_environments().await?;
    if envs.is_empty() {
        bail!(
            "No environments found. Create an environment first: joysafeterctl create environment"
        );
    }
    let env_idx = select_from_list(&envs, "name", "Select environment", false)?
        .expect("environment selection required");
    let env_id = envs[env_idx]["id"]
        .as_str()
        .context("environment response missing id")?
        .parse::<EnvironmentId>()
        .context("environment response contained a non-canonical id")?;
    let env_name = envs[env_idx]["name"].as_str().unwrap_or("?");

    let title = input_optional("Session title (optional)")?;

    println!("\n── Summary ──");
    println!("  Agent:       {} ({})", agent_name, agent_id);
    println!("  Environment: {} ({})", env_name, env_id);
    println!("  Title:       {}", title.as_deref().unwrap_or("-"));

    if !Confirm::new()
        .with_prompt("Create this session?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let mut authorization = SessionAuthorization::default();
    if !authorize_session_interactively(client, &agents[agent_idx], &mut authorization).await? {
        println!("Cancelled.");
        return Ok(());
    }
    let body = build_session_body(
        agent_id,
        Some(env_id),
        title.as_deref(),
        &[],
        &authorization.credential_group_ids,
    );
    let resp = authorization
        .create_session_with_rollback(client, &body)
        .await?;
    let session_id = resp["id"].as_str().unwrap_or("?");
    println!("\nsession/{} created", session_id);
    Ok(())
}

// ── Event ─────────────────────────────────────────────

async fn send_event(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Send Event ──\n");

    let sessions = client.list_sessions(Some(20), None).await?;
    if sessions.is_empty() {
        bail!("No sessions found. Create a session first: joysafeterctl create session");
    }

    let session_labels: Vec<String> = sessions
        .iter()
        .map(|s| {
            let id = s["id"].as_str().unwrap_or("?");
            let title = s["title"].as_str().unwrap_or("untitled");
            let status = s["status"].as_str().unwrap_or("?");
            format!("{} ({}) [{}]", id, title, status)
        })
        .collect();

    let session_idx = Select::new()
        .with_prompt("Select session")
        .items(&session_labels)
        .default(0)
        .interact()?;
    let session_id = sessions[session_idx]["id"]
        .as_str()
        .context("selected session missing id")?
        .parse::<SessionId>()
        .context("selected session returned a non-canonical session id")?;

    let event_types = vec!["user.message", "user.interrupt"];
    let type_idx = Select::new()
        .with_prompt("Event type")
        .items(&event_types)
        .default(0)
        .interact()?;
    let event_type = event_types[type_idx];

    let content = if event_type == "user.message" {
        Some(input_required("Message content")?)
    } else {
        None
    };

    println!("\n── Summary ──");
    println!("  Session: {}", session_id);
    println!("  Type:    {}", event_type);
    if let Some(ref c) = content {
        let preview: String = c.chars().take(100).collect();
        println!("  Content: {}", preview);
    }

    if !Confirm::new()
        .with_prompt("Send this event?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let body = if let Some(text) = content {
        serde_json::json!({
            "type": event_type,
            "content": [{"type": "text", "text": text}],
        })
    } else {
        serde_json::json!({
            "type": event_type,
        })
    };

    client.send_event(session_id, &body).await?;
    println!("\nevent sent to session/{}", session_id);
    Ok(())
}

// ── Memory Store ─────────────────────────────────────

async fn create_memory_store(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Memory Store ──\n");

    let name = input_required("Memory store name")?;
    let description = input_optional("Description (optional)")?;

    println!("\n── Summary ──");
    println!("  Name:        {}", name);
    println!("  Description: {}", description.as_deref().unwrap_or("-"));

    if !Confirm::new()
        .with_prompt("Create this memory store?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let mut body = serde_json::json!({ "name": name });
    if let Some(desc) = description {
        body["description"] = serde_json::Value::String(desc);
    }

    let resp = client.create_memory_store(&body).await?;
    let id = resp["id"].as_str().unwrap_or("?");
    println!("\nmemorystore/{} created ({})", name, id);
    Ok(())
}

// ── Memory ───────────────────────────────────────────

async fn create_memory(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Memory ──\n");

    let stores = client.list_memory_stores().await?;
    if stores.is_empty() {
        bail!("No memory stores found. Create one first: joysafeterctl create memory-store");
    }

    let store_labels: Vec<String> = stores
        .iter()
        .map(|s| {
            format!(
                "{} ({})",
                s["name"].as_str().unwrap_or("?"),
                s["id"].as_str().unwrap_or("?")
            )
        })
        .collect();

    let store_idx = Select::new()
        .with_prompt("Select memory store")
        .items(&store_labels)
        .default(0)
        .interact()?;
    let store_id = stores[store_idx]["id"]
        .as_str()
        .context("selected memory store missing id")?
        .parse::<MemoryStoreId>()
        .context("selected memory store returned a non-canonical id")?;

    let path = input_required("Memory path (e.g. /preferences/formatting.md)")?;

    let content = {
        let editor_result = open_in_editor(
            "# Enter memory content (save and close to continue)\n",
            "memory-content.md",
        );
        match editor_result {
            Ok(text) => {
                let trimmed = text.trim().to_string();
                if trimmed.is_empty()
                    || trimmed == "# Enter memory content (save and close to continue)"
                {
                    input_optional("Content (optional)")?
                } else {
                    Some(trimmed)
                }
            }
            _ => input_optional("Content (optional)")?,
        }
    };

    println!("\n── Summary ──");
    println!("  Store: {}", store_labels[store_idx]);
    println!("  Path:  {}", path);
    if let Some(ref c) = content {
        let preview: String = c.chars().take(80).collect();
        println!("  Content: {}...", preview);
    }

    if !Confirm::new()
        .with_prompt("Create this memory?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let mut body = serde_json::json!({ "path": path });
    if let Some(c) = content {
        body["content"] = serde_json::Value::String(c);
    }

    let resp = client.create_memory(store_id, &body).await?;
    let mem_id = resp["id"].as_str().unwrap_or("?");
    println!("\nmemory/{} created at {}", mem_id, path);
    Ok(())
}

// ── Credential group ─────────────────────────────────

async fn create_credential_group(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Credential Group ──\n");

    let name = input_required("Credential group name")?;
    let description = input_optional("Description (optional)")?;

    let mut body = serde_json::json!({ "name": name });
    if let Some(description) = description {
        body["description"] = serde_json::Value::String(description);
    }

    let resp = client.create_credential_group(&body).await?;
    println!(
        "\ncredential-group/{} created",
        resp["id"]
            .as_str()
            .unwrap_or(resp["name"].as_str().unwrap_or("?"))
    );
    Ok(())
}

async fn create_credential_group_member(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Credential Group Member ──\n");

    let groups = client.list_credential_groups().await?;
    if groups.is_empty() {
        bail!(
            "No credential groups found. Create one first: joysafeterctl create credential-group"
        );
    }
    let labels = groups
        .iter()
        .map(|v| {
            format!(
                "{} ({})",
                v["name"].as_str().unwrap_or("?"),
                v["id"].as_str().unwrap_or("?")
            )
        })
        .collect::<Vec<_>>();
    let idx = Select::new()
        .with_prompt("Select credential group")
        .items(&labels)
        .default(0)
        .interact()?;
    let group_id = groups[idx]["id"]
        .as_str()
        .ok_or_else(|| anyhow::anyhow!("Credential group response has no id"))?
        .parse::<CredentialGroupId>()
        .context("server returned a non-canonical credential group id")?;

    let resp = create_credential_group_member_interactively(client, group_id, None, None).await?;
    println!(
        "\ncredential/{} created",
        resp["id"].as_str().unwrap_or("?")
    );
    Ok(())
}

pub fn collect_mcp_servers() -> anyhow::Result<Vec<serde_json::Value>> {
    if !Confirm::new()
        .with_prompt("Add MCP servers?")
        .default(false)
        .interact()?
    {
        return Ok(vec![]);
    }

    let mut servers = Vec::new();
    loop {
        let types = vec![
            "streamable_http (remote HTTP endpoint)",
            "sse (remote event stream)",
            "local_stdio (local command)",
        ];
        let idx = Select::new()
            .with_prompt("MCP server type")
            .items(&types)
            .default(0)
            .interact()?;

        let name: String = Input::new().with_prompt("Server name").interact_text()?;
        let name = name.trim().to_string();
        if name.is_empty() {
            bail!("Server name cannot be empty");
        }

        let server = if idx <= 1 {
            let url: String = Input::new().with_prompt("Server URL").interact_text()?;
            let url = url.trim().to_string();
            if url.is_empty() {
                bail!("Server URL cannot be empty");
            }
            let auth_requirement = if idx == 0 {
                let requirements = [
                    "required (Session must select one matching credential)",
                    "optional (use a matching credential when selected)",
                    "none (never inject managed credentials)",
                ];
                let requirement_idx = Select::new()
                    .with_prompt("MCP authentication requirement")
                    .items(&requirements)
                    .default(0)
                    .interact()?;
                ["required", "optional", "none"][requirement_idx]
            } else {
                "none"
            };
            serde_json::json!({
                "type": if idx == 0 { "streamable_http" } else { "sse" },
                "name": name,
                "url": url,
                "auth_requirement": auth_requirement
            })
        } else {
            let command: String = Input::new().with_prompt("Command").interact_text()?;
            let command = command.trim().to_string();
            if command.is_empty() {
                bail!("Command cannot be empty");
            }
            let args_str: String = Input::new()
                .with_prompt("Args (comma-separated, empty to skip)")
                .allow_empty(true)
                .interact_text()?;
            let args: Vec<String> = args_str
                .split(',')
                .map(|a| a.trim().to_string())
                .filter(|a| !a.is_empty())
                .collect();
            serde_json::json!({"type": "local_stdio", "name": name, "command": command, "args": args})
        };

        let type_label = ["streamable_http", "sse", "local_stdio"][idx];
        println!(
            "  \x1b[0;32m✓\x1b[0m Added MCP server: {} ({})",
            name, type_label
        );
        servers.push(server);

        if !Confirm::new()
            .with_prompt("Add another MCP server?")
            .default(false)
            .interact()?
        {
            break;
        }
    }
    Ok(servers)
}

pub fn collect_custom_tools() -> anyhow::Result<Vec<serde_json::Value>> {
    if !Confirm::new()
        .with_prompt("Add custom tools?")
        .default(false)
        .interact()?
    {
        return Ok(vec![]);
    }

    let mut tools = Vec::new();
    loop {
        let name: String = Input::new().with_prompt("Tool name").interact_text()?;
        let name = name.trim().to_string();
        if name.is_empty() {
            bail!("Tool name cannot be empty");
        }

        let description: String = Input::new().with_prompt("Description").interact_text()?;
        let description = description.trim().to_string();

        println!("  Define input parameters (JSON Schema properties):");
        let mut properties = serde_json::Map::new();
        let mut required: Vec<String> = Vec::new();

        loop {
            let param_name: String = Input::new()
                .with_prompt("  Parameter name (empty to finish)")
                .allow_empty(true)
                .interact_text()?;
            let param_name = param_name.trim().to_string();
            if param_name.is_empty() {
                break;
            }

            let param_types = vec!["string", "number", "boolean", "object", "array"];
            let type_idx = Select::new()
                .with_prompt(format!("  Type for '{}'", param_name))
                .items(&param_types)
                .default(0)
                .interact()?;

            let param_desc: String = Input::new()
                .with_prompt(format!("  Description for '{}'", param_name))
                .allow_empty(true)
                .interact_text()?;

            let mut prop = serde_json::json!({"type": param_types[type_idx]});
            if !param_desc.trim().is_empty() {
                prop["description"] = serde_json::Value::String(param_desc.trim().to_string());
            }
            properties.insert(param_name.clone(), prop);

            if Confirm::new()
                .with_prompt(format!("  Is '{}' required?", param_name))
                .default(true)
                .interact()?
            {
                required.push(param_name);
            }
        }

        let mut schema = serde_json::json!({
            "type": "object",
            "properties": properties,
        });
        if !required.is_empty() {
            schema["required"] = serde_json::json!(required);
        }

        let tool = serde_json::json!({
            "type": "custom",
            "name": name,
            "description": description,
            "input_schema": schema,
        });

        println!("  \x1b[0;32m✓\x1b[0m Added custom tool: {}", name);
        tools.push(tool);

        if !Confirm::new()
            .with_prompt("Add another custom tool?")
            .default(false)
            .interact()?
        {
            break;
        }
    }
    Ok(tools)
}
