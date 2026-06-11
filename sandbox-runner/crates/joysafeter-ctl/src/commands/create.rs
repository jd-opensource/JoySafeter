use crate::client::JoysafeterClient;
use crate::CreateResource;
use anyhow::bail;
use dialoguer::{Confirm, Input, Select};

pub async fn run(client: &JoysafeterClient, resource: &CreateResource) -> anyhow::Result<()> {
    match resource {
        CreateResource::Secret => create_secret(client).await,
        CreateResource::Environment => create_environment(client).await,
        CreateResource::Agent => create_agent(client).await,
        CreateResource::Session => create_session(client).await,
        CreateResource::Event => send_event(client).await,
        CreateResource::MemoryStore => create_memory_store(client).await,
        CreateResource::Memory => create_memory(client).await,
        CreateResource::Vault => create_vault(client).await,
        CreateResource::VaultCredential => create_vault_credential(client).await,
    }
}

fn input_required(prompt: &str) -> anyhow::Result<String> {
    let val: String = Input::new().with_prompt(prompt).interact_text()?;
    if val.trim().is_empty() {
        bail!("{} cannot be empty", prompt);
    }
    Ok(val.trim().to_string())
}

fn normalize_resource_id(id: &str) -> String {
    id.split_once('_')
        .map(|(_, rest)| rest)
        .unwrap_or(id)
        .to_string()
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

// ── Secret ────────────────────────────────────────────

async fn create_secret(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Secret ──\n");

    let name = input_required("Secret name")?;

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
        bail!("Secret must have at least one key-value pair");
    }

    let keys: Vec<&String> = data.keys().collect();
    println!("\n── Summary ──");
    println!("  Name: {}", name);
    println!(
        "  Keys: {}",
        keys.iter()
            .map(|k| k.as_str())
            .collect::<Vec<_>>()
            .join(", ")
    );

    if !Confirm::new()
        .with_prompt("Create this secret?")
        .default(true)
        .interact()?
    {
        println!("Cancelled.");
        return Ok(());
    }

    let body = serde_json::json!({
        "name": name,
        "data": serde_json::Value::Object(data),
    });
    client.create_secret(&body).await?;
    println!("\nsecret/{} created", name);
    Ok(())
}

// ── Environment ───────────────────────────────────────

async fn create_environment(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Environment ──\n");

    let name = input_required("Environment name")?;

    let net_types = vec!["unrestricted", "limited"];
    let net_idx = Select::new()
        .with_prompt("Networking type")
        .items(&net_types)
        .default(0)
        .interact()?;
    let net_type = net_types[net_idx];

    let mut allowed_hosts: Vec<String> = Vec::new();
    if net_type == "limited" {
        loop {
            if let Some(host) = input_optional("Allowed host (Enter to finish)")? {
                allowed_hosts.push(host);
            } else {
                break;
            }
        }
    }

    println!("\n── Summary ──");
    println!("  Name:       {}", name);
    println!("  Networking: {}", net_type);
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

    let mut networking = serde_json::json!({"type": net_type});
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

    let engines = vec!["claude", "codex"];
    let engine_idx = Select::new()
        .with_prompt("Engine")
        .items(&engines)
        .default(0)
        .interact()?;
    let engine = engines[engine_idx];

    let model = input_required("Model (e.g. Claude-Sonnet-4.6)")?;
    let description = input_optional("Description (optional)")?;

    let system_prompt = {
        let editor_result = dialoguer::Editor::new()
            .require_save(true)
            .edit("# Enter system prompt (save and close to continue)\n");
        match editor_result {
            Ok(Some(text)) => {
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

    let secret_ref = {
        let secrets = client.list_secrets().await.unwrap_or_default();
        if secrets.is_empty() {
            println!("  (No secrets found, skipping secret_ref)");
            None
        } else {
            match select_from_list(&secrets, "name", "Secret ref", true)? {
                Some(idx) => secrets[idx]["name"].as_str().map(|s| s.to_string()),
                None => None,
            }
        }
    };

    let environment_ref = {
        let envs = client.list_environments().await.unwrap_or_default();
        if envs.is_empty() {
            println!("  (No environments found, skipping environment_ref)");
            None
        } else {
            match select_from_list(&envs, "name", "Environment ref", true)? {
                Some(idx) => envs[idx]["name"].as_str().map(|s| s.to_string()),
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
    println!("  Secret Ref:    {}", secret_ref.as_deref().unwrap_or("-"));
    println!(
        "  Environment:   {}",
        environment_ref.as_deref().unwrap_or("-")
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
    if let Some(sr) = secret_ref {
        body["secret_ref"] = serde_json::Value::String(sr);
    }
    if let Some(er) = environment_ref {
        body["environment_ref"] = serde_json::Value::String(er);
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
    let agent_id = normalize_resource_id(agents[agent_idx]["id"].as_str().unwrap());
    let agent_name = agents[agent_idx]["name"].as_str().unwrap_or("?");

    let envs = client.list_environments().await?;
    if envs.is_empty() {
        bail!(
            "No environments found. Create an environment first: joysafeterctl create environment"
        );
    }
    let env_idx = select_from_list(&envs, "name", "Select environment", false)?
        .expect("environment selection required");
    let env_id = normalize_resource_id(envs[env_idx]["id"].as_str().unwrap());
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

    let mut body = serde_json::json!({
        "agent_id": agent_id,
        "environment_id": env_id,
    });
    if let Some(t) = title {
        body["title"] = serde_json::Value::String(t);
    }

    let resp = client.create_session(&body).await?;
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
    let session_id = sessions[session_idx]["id"].as_str().unwrap().to_string();

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

    client.send_event(&session_id, &body).await?;
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
    let store_id = stores[store_idx]["id"].as_str().unwrap().to_string();

    let path = input_required("Memory path (e.g. /preferences/formatting.md)")?;

    let content = {
        let editor_result = dialoguer::Editor::new()
            .require_save(true)
            .edit("# Enter memory content (save and close to continue)\n");
        match editor_result {
            Ok(Some(text)) => {
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

    let resp = client.create_memory(&store_id, &body).await?;
    let mem_id = resp["id"].as_str().unwrap_or("?");
    println!("\nmemory/{} created at {}", mem_id, path);
    Ok(())
}

// ── Vault ────────────────────────────────────────────

async fn create_vault(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Vault ──\n");

    let name = input_required("Vault name")?;
    let description = input_optional("Description (optional)")?;

    let mut body = serde_json::json!({ "name": name });
    if let Some(description) = description {
        body["description"] = serde_json::Value::String(description);
    }

    let resp = client.create_vault(&body).await?;
    println!(
        "\nvault/{} created",
        resp["id"]
            .as_str()
            .unwrap_or(resp["name"].as_str().unwrap_or("?"))
    );
    Ok(())
}

async fn create_vault_credential(client: &JoysafeterClient) -> anyhow::Result<()> {
    println!("\n── Create Vault Credential ──\n");

    let vaults = client.list_vaults().await?;
    if vaults.is_empty() {
        bail!("No vaults found. Create one first: joysafeterctl create vault");
    }
    let labels = vaults
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
        .with_prompt("Select vault")
        .items(&labels)
        .default(0)
        .interact()?;
    let vault_id = vaults[idx]["id"].as_str().unwrap().to_string();

    let name = input_required("Credential name")?;
    let mcp_server_url = input_required("MCP server URL")?;
    let token_value = input_required("Bearer token value")?;

    let body = serde_json::json!({
        "name": name,
        "credential_type": "static_bearer",
        "mcp_server_url": mcp_server_url,
        "token_value": token_value,
    });
    let resp = client.create_vault_credential(&vault_id, &body).await?;
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
        let types = vec!["url (remote HTTP endpoint)", "stdio (local command)"];
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

        let server = if idx == 0 {
            let url: String = Input::new().with_prompt("Server URL").interact_text()?;
            let url = url.trim().to_string();
            if url.is_empty() {
                bail!("Server URL cannot be empty");
            }
            serde_json::json!({"type": "url", "name": name, "url": url})
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
            serde_json::json!({"type": "stdio", "name": name, "command": command, "args": args})
        };

        let type_label = if idx == 0 { "url" } else { "stdio" };
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
