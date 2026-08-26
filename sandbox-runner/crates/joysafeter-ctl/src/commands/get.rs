use crate::client::JoysafeterClient;
use crate::output::print_table;
use crate::GetResource;
use crate::OutputFormat;
use anyhow::Context;
use joysafeter_entity_id::AgentId;

pub async fn run(
    client: &JoysafeterClient,
    resource: &GetResource,
    format: &OutputFormat,
) -> anyhow::Result<()> {
    match resource {
        GetResource::Agents => {
            let agents = client.list_agents().await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&agents)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = agents
                        .iter()
                        .map(|a| {
                            let model = if a["model"].is_object() {
                                a["model"]["id"].as_str().unwrap_or("-").to_string()
                            } else {
                                a["model"].as_str().unwrap_or("-").to_string()
                            };
                            vec![
                                a["name"].as_str().unwrap_or("-").to_string(),
                                a["engine_kind"].as_str().unwrap_or("-").to_string(),
                                model,
                                a["model_credential_id"].as_str().unwrap_or("-").to_string(),
                                a["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(
                        &["NAME", "ENGINE", "MODEL", "MODEL_CREDENTIAL_ID", "CREATED"],
                        &rows,
                    );
                }
            }
        }
        GetResource::Agent { name } => {
            let agent = client
                .get_agent_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", name))?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&agent)?),
                OutputFormat::Table => {
                    println!("Name:          {}", agent["name"].as_str().unwrap_or("-"));
                    println!(
                        "Engine:        {}",
                        agent["engine_kind"].as_str().unwrap_or("-")
                    );
                    let model = if agent["model"].is_object() {
                        agent["model"]["id"].as_str().unwrap_or("-")
                    } else {
                        agent["model"].as_str().unwrap_or("-")
                    };
                    println!("Model:         {}", model);
                    println!(
                        "Model Credential ID: {}",
                        agent["model_credential_id"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Environment ID: {}",
                        agent["environment_id"].as_str().unwrap_or("-")
                    );
                    println!(
                        "System Prompt: {}",
                        agent["system"]
                            .as_str()
                            .unwrap_or("-")
                            .chars()
                            .take(80)
                            .collect::<String>()
                    );
                    println!("Version:       {}", agent["version"]);
                    println!("ID:            {}", agent["id"].as_str().unwrap_or("-"));
                    println!(
                        "Created:       {}",
                        agent["created_at"].as_str().unwrap_or("-")
                    );
                }
            }
        }
        GetResource::Environments => {
            let envs = client.list_environments().await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&envs)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = envs
                        .iter()
                        .map(|e| {
                            let network_type = e["config"]["networking"]["type"]
                                .as_str()
                                .unwrap_or("unrestricted")
                                .to_string();
                            vec![
                                e["name"].as_str().unwrap_or("-").to_string(),
                                e["id"].as_str().unwrap_or("-").to_string(),
                                network_type,
                                e["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["NAME", "ID", "NETWORKING", "CREATED"], &rows);
                }
            }
        }
        GetResource::Environment { name } => {
            let env = client
                .get_environment_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Environment '{}' not found", name))?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&env)?),
                OutputFormat::Table => {
                    println!("Name:        {}", env["name"].as_str().unwrap_or("-"));
                    println!("ID:          {}", env["id"].as_str().unwrap_or("-"));
                    println!(
                        "Description: {}",
                        env["description"].as_str().unwrap_or("-")
                    );
                    let network_type = env["config"]["networking"]["type"]
                        .as_str()
                        .unwrap_or("unrestricted");
                    println!("Networking:  {}", network_type);
                    if let Some(hosts) = env["config"]["networking"]["allowed_hosts"].as_array() {
                        let hosts_str: Vec<&str> =
                            hosts.iter().filter_map(|h| h.as_str()).collect();
                        if !hosts_str.is_empty() {
                            println!("Allowed:     {}", hosts_str.join(", "));
                        }
                    }
                    println!("Created:     {}", env["created_at"].as_str().unwrap_or("-"));
                }
            }
        }
        GetResource::Sessions { agent, limit } => {
            let agent_id = if let Some(agent_name) = agent {
                let a = client
                    .get_agent_by_name(agent_name)
                    .await?
                    .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", agent_name))?;
                Some(
                    a["id"]
                        .as_str()
                        .context("agent response missing id")?
                        .parse::<AgentId>()
                        .context("agent response returned a non-canonical agent id")?,
                )
            } else {
                None
            };
            let sessions = client.list_sessions(*limit, agent_id).await?;
            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&sessions)?)
                }
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = sessions
                        .iter()
                        .map(|s| {
                            let usage = s.get("usage");
                            let input = usage.and_then(|u| u["input_tokens"].as_i64()).unwrap_or(0);
                            let output =
                                usage.and_then(|u| u["output_tokens"].as_i64()).unwrap_or(0);
                            vec![
                                s["id"].as_str().unwrap_or("-").to_string(),
                                s["status"].as_str().unwrap_or("-").to_string(),
                                s["title"].as_str().unwrap_or("-").to_string(),
                                format!("{}/{}", input, output),
                                s["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["ID", "STATUS", "TITLE", "TOKENS(I/O)", "CREATED"], &rows);
                }
            }
        }
        GetResource::Session { id } => {
            let session = client.get_session(*id).await?;
            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&session)?)
                }
                OutputFormat::Table => {
                    println!("ID:          {}", session["id"].as_str().unwrap_or("-"));
                    println!("Status:      {}", session["status"].as_str().unwrap_or("-"));
                    println!("Title:       {}", session["title"].as_str().unwrap_or("-"));
                    if let Some(agent) = session.get("agent") {
                        println!("Agent:       {}", agent["name"].as_str().unwrap_or("-"));
                    }
                    if let Some(env_id) = session["environment_id"].as_str() {
                        println!("Environment: {}", env_id);
                    }
                    if let Some(sr) = session.get("stop_reason") {
                        if !sr.is_null() {
                            println!("Stop Reason: {}", sr["type"].as_str().unwrap_or("-"));
                        }
                    }
                    if let Some(usage) = session.get("usage") {
                        if !usage.is_null() {
                            let input = usage["input_tokens"].as_i64().unwrap_or(0);
                            let output = usage["output_tokens"].as_i64().unwrap_or(0);
                            let cache_create =
                                usage["cache_creation_input_tokens"].as_i64().unwrap_or(0);
                            let cache_read = usage["cache_read_input_tokens"].as_i64().unwrap_or(0);
                            println!("─── Token Usage ───");
                            println!("  Input:        {}", input);
                            println!("  Output:       {}", output);
                            println!("  Cache Create: {}", cache_create);
                            println!("  Cache Read:   {}", cache_read);
                            println!("  Total:        {}", input + output);
                        }
                    }
                    println!(
                        "Created:     {}",
                        session["created_at"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Updated:     {}",
                        session["updated_at"].as_str().unwrap_or("-")
                    );
                }
            }
        }
        GetResource::Events { session, limit } => {
            let events = client.list_events(*session, *limit).await?;
            match format {
                OutputFormat::Json => {
                    println!("{}", serde_json::to_string_pretty(&events)?)
                }
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = events
                        .iter()
                        .map(|e| {
                            let seq = e["seq"]
                                .as_i64()
                                .map(|n| n.to_string())
                                .unwrap_or_else(|| "-".to_string());
                            let snippet = match e["type"].as_str().unwrap_or("") {
                                "user.message" | "agent.message" => {
                                    if let Some(arr) = e["content"].as_array() {
                                        arr.first()
                                            .and_then(|b| b["text"].as_str())
                                            .unwrap_or("")
                                            .chars()
                                            .take(60)
                                            .collect()
                                    } else {
                                        e["content"]
                                            .as_str()
                                            .unwrap_or("")
                                            .chars()
                                            .take(60)
                                            .collect()
                                    }
                                }
                                t if t.contains("tool_use") => {
                                    format!(
                                        "{}({})",
                                        e["name"].as_str().unwrap_or("?"),
                                        e["input"]
                                            .as_str()
                                            .unwrap_or("")
                                            .chars()
                                            .take(30)
                                            .collect::<String>()
                                    )
                                }
                                _ => String::new(),
                            };
                            vec![seq, e["type"].as_str().unwrap_or("-").to_string(), snippet]
                        })
                        .collect();
                    print_table(&["SEQ", "TYPE", "CONTENT"], &rows);
                }
            }
        }
        GetResource::Tasks { agent } => {
            let agent_name = agent
                .as_deref()
                .ok_or_else(|| anyhow::anyhow!("--agent flag is required for listing tasks"))?;
            let agent_json = client
                .get_agent_by_name(agent_name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", agent_name))?;
            let agent_id = agent_json["id"]
                .as_str()
                .context("agent response missing id")?
                .parse::<AgentId>()
                .context("agent response returned a non-canonical agent id")?;
            let tasks = client.list_tasks_by_agent(agent_id).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&tasks)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = tasks
                        .iter()
                        .map(|t| {
                            vec![
                                t["id"].as_str().unwrap_or("-").chars().take(36).collect(),
                                t["status"].as_str().unwrap_or("-").to_string(),
                                t["prompt"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(40)
                                    .collect(),
                                t["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["ID", "STATUS", "PROMPT", "CREATED"], &rows);
                }
            }
        }
        GetResource::Task { id } => {
            let task = client.get_task(*id).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&task)?),
                OutputFormat::Table => {
                    println!("ID:      {}", task["id"].as_str().unwrap_or("-"));
                    println!("Status:  {}", task["status"].as_str().unwrap_or("-"));
                    println!("Agent:   {}", task["agent_id"].as_str().unwrap_or("-"));
                    println!(
                        "Prompt:  {}",
                        task["prompt"]
                            .as_str()
                            .unwrap_or("-")
                            .chars()
                            .take(100)
                            .collect::<String>()
                    );
                    if let Some(output) = task["output"].as_str() {
                        if !output.is_empty() {
                            println!(
                                "Output:  {}...",
                                output.chars().take(200).collect::<String>()
                            );
                        }
                    }
                    if let Some(err) = task["error"].as_str() {
                        if !err.is_empty() {
                            println!("Error:   {}", err);
                        }
                    }
                    println!("Created: {}", task["created_at"].as_str().unwrap_or("-"));
                }
            }
        }
        GetResource::Credentials => {
            let credentials = client.list_credentials().await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&credentials)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = credentials
                        .iter()
                        .map(|credential| {
                            vec![
                                credential["id"].as_str().unwrap_or("-").to_string(),
                                credential["kind"].as_str().unwrap_or("-").to_string(),
                                credential["name"].as_str().unwrap_or("-").to_string(),
                                credential["provider"].as_str().unwrap_or("-").to_string(),
                                credential["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["ID", "KIND", "NAME", "PROVIDER", "CREATED"], &rows);
                }
            }
        }
        GetResource::MemoryStores => {
            let stores = client.list_memory_stores().await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&stores)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = stores
                        .iter()
                        .map(|s| {
                            vec![
                                s["id"].as_str().unwrap_or("-").to_string(),
                                s["name"].as_str().unwrap_or("-").to_string(),
                                s["description"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(40)
                                    .collect(),
                                s["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["ID", "NAME", "DESCRIPTION", "CREATED"], &rows);
                }
            }
        }
        GetResource::MemoryStore { id } => {
            let store = client.get_memory_store(*id).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&store)?),
                OutputFormat::Table => {
                    println!("ID:          {}", store["id"].as_str().unwrap_or("-"));
                    println!("Name:        {}", store["name"].as_str().unwrap_or("-"));
                    println!(
                        "Description: {}",
                        store["description"].as_str().unwrap_or("-")
                    );
                    if let Some(metadata) = store.get("metadata") {
                        if metadata.is_object() && !metadata.as_object().unwrap().is_empty() {
                            println!("Metadata:    {}", metadata);
                        }
                    }
                    println!(
                        "Created:     {}",
                        store["created_at"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Updated:     {}",
                        store["updated_at"].as_str().unwrap_or("-")
                    );
                    if let Some(archived) = store["archived_at"].as_str() {
                        println!("Archived:    {}", archived);
                    }
                    let memories = client.list_memories(*id).await?;
                    if !memories.is_empty() {
                        println!("\n─── Memories ({}) ───", memories.len());
                        let rows: Vec<Vec<String>> = memories
                            .iter()
                            .map(|m| {
                                vec![
                                    m["id"].as_str().unwrap_or("-").to_string(),
                                    m["path"].as_str().unwrap_or("-").to_string(),
                                    format!(
                                        "{}",
                                        m["content_size_bytes"]
                                            .as_i64()
                                            .or_else(|| m["size_bytes"].as_i64())
                                            .unwrap_or(0)
                                    ),
                                    m["updated_at"]
                                        .as_str()
                                        .unwrap_or("-")
                                        .chars()
                                        .take(19)
                                        .collect(),
                                ]
                            })
                            .collect();
                        print_table(&["ID", "PATH", "SIZE", "UPDATED"], &rows);
                    }
                }
            }
        }
        GetResource::Memories { store } => {
            let memories = client.list_memories(*store).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&memories)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = memories
                        .iter()
                        .map(|m| {
                            vec![
                                m["id"].as_str().unwrap_or("-").to_string(),
                                m["path"].as_str().unwrap_or("-").to_string(),
                                format!(
                                    "{}",
                                    m["content_size_bytes"]
                                        .as_i64()
                                        .or_else(|| m["size_bytes"].as_i64())
                                        .unwrap_or(0)
                                ),
                                m["updated_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["ID", "PATH", "SIZE", "UPDATED"], &rows);
                }
            }
        }
        GetResource::Memory { store, id } => {
            let memory = client.get_memory(*store, *id).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&memory)?),
                OutputFormat::Table => {
                    println!("ID:      {}", memory["id"].as_str().unwrap_or("-"));
                    println!("Path:    {}", memory["path"].as_str().unwrap_or("-"));
                    println!(
                        "Store:   {}",
                        memory["store_id"]
                            .as_str()
                            .or_else(|| memory["memory_store_id"].as_str())
                            .unwrap_or("-")
                    );
                    println!(
                        "Size:    {} bytes",
                        memory["content_size_bytes"]
                            .as_i64()
                            .or_else(|| memory["size_bytes"].as_i64())
                            .unwrap_or(0)
                    );
                    println!(
                        "SHA256:  {}",
                        memory["content_sha256"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Version: {}",
                        memory["memory_version_id"]
                            .as_str()
                            .or_else(|| memory["current_version_id"].as_str())
                            .unwrap_or("-")
                    );
                    println!("Created: {}", memory["created_at"].as_str().unwrap_or("-"));
                    println!("Updated: {}", memory["updated_at"].as_str().unwrap_or("-"));
                    if let Some(content) = memory["content"].as_str() {
                        println!("\n─── Content ───");
                        println!("{}", content);
                    }
                }
            }
        }
        GetResource::MemoryVersions { store } => {
            let versions = client.list_memory_versions(*store).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&versions)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = versions
                        .iter()
                        .map(|v| {
                            vec![
                                v["id"].as_str().unwrap_or("-").to_string(),
                                v["memory_id"].as_str().unwrap_or("-").to_string(),
                                v["operation"].as_str().unwrap_or("-").to_string(),
                                v["path"].as_str().unwrap_or("-").to_string(),
                                v["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["ID", "MEMORY_ID", "OPERATION", "PATH", "CREATED"], &rows);
                }
            }
        }
        GetResource::Credential { id } => {
            let credential = client.get_credential(*id).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&credential)?),
                OutputFormat::Table => {
                    println!("ID:       {}", credential["id"].as_str().unwrap_or("-"));
                    println!("Kind:     {}", credential["kind"].as_str().unwrap_or("-"));
                    println!("Name:     {}", credential["name"].as_str().unwrap_or("-"));
                    println!(
                        "Provider: {}",
                        credential["provider"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Protocol: {}",
                        credential["protocol"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Created:  {}",
                        credential["created_at"].as_str().unwrap_or("-")
                    );
                }
            }
        }
        GetResource::CredentialGroups => {
            let groups = client.list_credential_groups().await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&groups)?),
                OutputFormat::Table => {
                    let rows = groups
                        .iter()
                        .map(|v| {
                            vec![
                                v["id"].as_str().unwrap_or("-").to_string(),
                                v["name"].as_str().unwrap_or("-").to_string(),
                                v["description"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(40)
                                    .collect(),
                                v["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect::<Vec<_>>();
                    print_table(&["ID", "NAME", "DESCRIPTION", "CREATED"], &rows);
                }
            }
        }
        GetResource::CredentialGroup { id } => {
            let group = client.get_credential_group(*id).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&group)?),
                OutputFormat::Table => {
                    println!("ID:          {}", group["id"].as_str().unwrap_or("-"));
                    println!("Name:        {}", group["name"].as_str().unwrap_or("-"));
                    println!(
                        "Description: {}",
                        group["description"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Created:     {}",
                        group["created_at"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Updated:     {}",
                        group["updated_at"].as_str().unwrap_or("-")
                    );
                }
            }
        }
        GetResource::CredentialGroupMembers { group } => {
            let credentials = client.list_credential_group_members(*group).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&credentials)?),
                OutputFormat::Table => {
                    let rows = credentials
                        .iter()
                        .map(|c| {
                            vec![
                                c["id"].as_str().unwrap_or("-").to_string(),
                                c["name"].as_str().unwrap_or("-").to_string(),
                                c["auth_scheme"].as_str().unwrap_or("-").to_string(),
                                c["mcp_server_url"].as_str().unwrap_or("-").to_string(),
                                c["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect::<Vec<_>>();
                    print_table(&["ID", "NAME", "AUTH", "MCP URL", "CREATED"], &rows);
                }
            }
        }
    }
    Ok(())
}
