use crate::client::JoysafeterClient;
use crate::output::print_table;
use crate::GetResource;
use crate::OutputFormat;

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
                                a["secret_ref"].as_str().unwrap_or("-").to_string(),
                                a["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["NAME", "ENGINE", "MODEL", "SECRET_REF", "CREATED"], &rows);
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
                        "Secret Ref:    {}",
                        agent["secret_ref"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Env Ref:       {}",
                        agent["environment_ref"].as_str().unwrap_or("-")
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
                let id_str = a["id"].as_str().unwrap_or("");
                let raw = id_str.strip_prefix("agent_").unwrap_or(id_str);
                Some(raw.to_string())
            } else {
                None
            };
            let sessions = client.list_sessions(*limit, agent_id.as_deref()).await?;
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
            let session = client.get_session(id).await?;
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
            let events = client.list_events(session, *limit).await?;
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
            let agent_id = agent_json["id"].as_str().unwrap();
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
            let task = client.get_task(id).await?;
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
        GetResource::Secrets => {
            let secrets = client.list_secrets().await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&secrets)?),
                OutputFormat::Table => {
                    let rows: Vec<Vec<String>> = secrets
                        .iter()
                        .map(|s| {
                            let keys = s["keys"]
                                .as_array()
                                .map(|arr| {
                                    arr.iter()
                                        .filter_map(|v| v.as_str())
                                        .collect::<Vec<_>>()
                                        .join(", ")
                                })
                                .unwrap_or_else(|| "-".to_string());
                            vec![
                                s["name"].as_str().unwrap_or("-").to_string(),
                                keys,
                                s["created_at"]
                                    .as_str()
                                    .unwrap_or("-")
                                    .chars()
                                    .take(19)
                                    .collect(),
                            ]
                        })
                        .collect();
                    print_table(&["NAME", "KEYS", "CREATED"], &rows);
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
            let store = client.get_memory_store(id).await?;
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
                    let memories = client.list_memories(id).await?;
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
            let memories = client.list_memories(store).await?;
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
            let memory = client.get_memory(store, id).await?;
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
            let versions = client.list_memory_versions(store).await?;
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
        GetResource::Secret { name } => {
            let secret = client
                .get_secret_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Secret '{}' not found", name))?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&secret)?),
                OutputFormat::Table => {
                    println!("Name:    {}", secret["name"].as_str().unwrap_or("-"));
                    let keys = secret["keys"]
                        .as_array()
                        .map(|arr| {
                            arr.iter()
                                .filter_map(|v| v.as_str())
                                .collect::<Vec<_>>()
                                .join(", ")
                        })
                        .unwrap_or_else(|| "-".to_string());
                    println!("Keys:    {}", keys);
                    println!("ID:      {}", secret["id"].as_str().unwrap_or("-"));
                    println!("Created: {}", secret["created_at"].as_str().unwrap_or("-"));
                }
            }
        }
        GetResource::Vaults => {
            let vaults = client.list_vaults().await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&vaults)?),
                OutputFormat::Table => {
                    let rows = vaults
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
        GetResource::Vault { id } => {
            let vault = client.get_vault(id).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&vault)?),
                OutputFormat::Table => {
                    println!("ID:          {}", vault["id"].as_str().unwrap_or("-"));
                    println!("Name:        {}", vault["name"].as_str().unwrap_or("-"));
                    println!(
                        "Description: {}",
                        vault["description"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Created:     {}",
                        vault["created_at"].as_str().unwrap_or("-")
                    );
                    println!(
                        "Updated:     {}",
                        vault["updated_at"].as_str().unwrap_or("-")
                    );
                }
            }
        }
        GetResource::VaultCredentials { vault } => {
            let creds = client.list_vault_credentials(vault).await?;
            match format {
                OutputFormat::Json => println!("{}", serde_json::to_string_pretty(&creds)?),
                OutputFormat::Table => {
                    let rows = creds
                        .iter()
                        .map(|c| {
                            vec![
                                c["id"].as_str().unwrap_or("-").to_string(),
                                c["name"].as_str().unwrap_or("-").to_string(),
                                c["credential_type"].as_str().unwrap_or("-").to_string(),
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
                    print_table(&["ID", "NAME", "TYPE", "MCP URL", "CREATED"], &rows);
                }
            }
        }
    }
    Ok(())
}
