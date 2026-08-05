use crate::client::JoysafeterClient;
use crate::manifest::{self, parse_duration, Resource};
use anyhow::Context;
use base64::Engine;
use std::path::Path;

pub async fn run(client: &JoysafeterClient, file: &str) -> anyhow::Result<()> {
    let resources = manifest::parse_manifests(file)?;

    let mut secrets = Vec::new();
    let mut agents = Vec::new();
    let mut tasks = Vec::new();
    let mut environments = Vec::new();
    let mut memory_stores = Vec::new();
    for r in resources {
        match r {
            Resource::Secret(s) => secrets.push(s),
            Resource::Agent(a) => agents.push(a),
            Resource::Task(t) => tasks.push(t),
            Resource::Environment(e) => environments.push(e),
            Resource::MemoryStore(m) => memory_stores.push(m),
        }
    }

    for manifest in &secrets {
        apply_secret(client, manifest).await?;
    }
    for manifest in &environments {
        apply_environment(client, manifest).await?;
    }
    for manifest in &memory_stores {
        apply_memory_store(client, manifest).await?;
    }
    for manifest in &agents {
        apply_agent(client, manifest).await?;
    }
    for manifest in &tasks {
        apply_task(client, manifest).await?;
    }

    Ok(())
}

async fn apply_secret(
    client: &JoysafeterClient,
    manifest: &manifest::SecretManifest,
) -> anyhow::Result<()> {
    let name = &manifest.metadata.name;
    let existing = client.get_secret_by_name(name).await?;

    match existing {
        Some(secret) => {
            let id = secret["id"].as_str().unwrap();
            let body = serde_json::json!({
                "data": manifest.spec.data,
            });
            client.update_secret(id, &body).await?;
            println!("secret/{name} configured (updated)");
        }
        None => {
            let body = serde_json::json!({
                "name": name,
                "data": manifest.spec.data,
            });
            client.create_secret(&body).await?;
            println!("secret/{name} created");
        }
    }
    Ok(())
}

fn pack_dir(path: &Path) -> anyhow::Result<String> {
    anyhow::ensure!(path.is_dir(), "Path is not a directory: {}", path.display());
    let mut buf = Vec::new();
    {
        let gz = flate2::write::GzEncoder::new(&mut buf, flate2::Compression::default());
        let mut tar = tar::Builder::new(gz);
        tar.append_dir_all(".", path)
            .with_context(|| format!("Failed to tar dir: {}", path.display()))?;
        tar.into_inner()?.finish()?;
    }
    Ok(base64::engine::general_purpose::STANDARD.encode(&buf))
}

async fn apply_agent(
    client: &JoysafeterClient,
    manifest: &manifest::AgentManifest,
) -> anyhow::Result<()> {
    let name = &manifest.metadata.name;
    let existing = client.get_agent_by_name(name).await?;

    let mcp_servers: Vec<serde_json::Value> = manifest
        .spec
        .mcp_servers
        .iter()
        .map(|s| match s {
            manifest::McpServerSpec::Stdio {
                name,
                command,
                args,
                env,
            } => {
                serde_json::json!({
                    "type": "stdio",
                    "name": name,
                    "command": command,
                    "args": args,
                    "env": env,
                })
            }
            manifest::McpServerSpec::Url { name, url } => {
                serde_json::json!({
                    "type": "url",
                    "name": name,
                    "url": url,
                })
            }
        })
        .collect();

    let pack_items = |items: &[manifest::InjectSpec]| -> Vec<serde_json::Value> {
        items
            .iter()
            .map(|s| {
                let tar_gz_b64 = pack_dir(Path::new(&s.path))
                    .with_context(|| format!("Failed to pack '{}' at {}", s.name, s.path))
                    .unwrap();
                serde_json::json!({
                    "name": s.name,
                    "tar_gz_b64": tar_gz_b64,
                })
            })
            .collect()
    };
    let skills_packed = pack_items(&manifest.spec.skills);
    let agents_packed = pack_items(&manifest.spec.agents);
    let commands_packed = pack_items(&manifest.spec.commands);

    let tools: Vec<serde_json::Value> = manifest
        .spec
        .tools
        .iter()
        .map(|t| match t {
            manifest::AgentToolSpec::AgentToolset {
                default_config,
                configs,
            } => {
                let mut tool = serde_json::json!({"type": "agent_toolset_20260401"});
                if let Some(ref dc) = default_config {
                    let mut config = serde_json::Map::new();
                    if let Some(ref pp) = dc.permission_policy {
                        config.insert(
                            "permission_policy".into(),
                            serde_json::json!({"type": pp.policy_type}),
                        );
                    }
                    if let Some(enabled) = dc.enabled {
                        config.insert("enabled".into(), serde_json::Value::Bool(enabled));
                    }
                    tool["default_config"] = serde_json::Value::Object(config);
                }
                if !configs.is_empty() {
                    let cfgs: Vec<serde_json::Value> = configs
                        .iter()
                        .map(|c| serde_json::json!({"name": c.name, "enabled": c.enabled}))
                        .collect();
                    tool["configs"] = serde_json::Value::Array(cfgs);
                }
                tool
            }
            manifest::AgentToolSpec::Custom {
                name,
                description,
                input_schema,
            } => {
                serde_json::json!({
                    "type": "custom",
                    "name": name,
                    "description": description,
                    "input_schema": input_schema,
                })
            }
            manifest::AgentToolSpec::McpToolset {
                mcp_server_name,
                default_config,
                configs,
            } => {
                let mut tool =
                    serde_json::json!({"type": "mcp_toolset", "mcp_server_name": mcp_server_name});
                if let Some(ref dc) = default_config {
                    let mut config = serde_json::Map::new();
                    if let Some(ref pp) = dc.permission_policy {
                        config.insert(
                            "permission_policy".into(),
                            serde_json::json!({"type": pp.policy_type}),
                        );
                    }
                    if let Some(enabled) = dc.enabled {
                        config.insert("enabled".into(), serde_json::Value::Bool(enabled));
                    }
                    tool["default_config"] = serde_json::Value::Object(config);
                }
                if !configs.is_empty() {
                    let cfgs: Vec<serde_json::Value> = configs
                        .iter()
                        .map(|c| serde_json::json!({"name": c.name, "enabled": c.enabled}))
                        .collect();
                    tool["configs"] = serde_json::Value::Array(cfgs);
                }
                tool
            }
        })
        .collect();

    match existing {
        Some(agent) => {
            let id = agent["id"].as_str().unwrap();
            let version = agent["version"].as_i64();
            let mut body = serde_json::json!({
                "engine_kind": manifest.spec.engine_kind,
                "model": manifest.spec.model,
                "system": manifest.spec.system_prompt,
                "description": manifest.spec.description,
                "env": manifest.spec.env,
                "mcp_servers": mcp_servers,
                "skills": skills_packed,
                "agents": agents_packed,
                "commands": commands_packed,
                "tools": tools,
                "secret_ref": manifest.spec.secret_ref,
            });
            if let Some(v) = version {
                body["version"] = serde_json::Value::Number(v.into());
            }
            if let Some(ref er) = manifest.spec.environment_ref {
                body["environment_ref"] = serde_json::Value::String(er.clone());
            }
            client.update_agent(id, &body).await?;
            println!("agent/{name} configured (updated)");
        }
        None => {
            let mut body = serde_json::json!({
                "name": name,
                "engine_kind": manifest.spec.engine_kind,
                "model": manifest.spec.model,
                "system": manifest.spec.system_prompt,
                "description": manifest.spec.description,
                "env": manifest.spec.env,
                "mcp_servers": mcp_servers,
                "skills": skills_packed,
                "agents": agents_packed,
                "commands": commands_packed,
                "tools": tools,
                "secret_ref": manifest.spec.secret_ref,
            });
            if let Some(ref er) = manifest.spec.environment_ref {
                body["environment_ref"] = serde_json::Value::String(er.clone());
            }
            client.create_agent(&body).await?;
            println!("agent/{name} created");
        }
    }
    Ok(())
}

async fn apply_environment(
    client: &JoysafeterClient,
    manifest: &manifest::EnvironmentManifest,
) -> anyhow::Result<()> {
    let name = &manifest.metadata.name;
    let existing = client.get_environment_by_name(name).await?;

    let config = build_environment_config(&manifest.spec);

    match existing {
        Some(env) => {
            let id = env["id"].as_str().unwrap();
            let body = serde_json::json!({
                "config": config,
            });
            client.update_environment(id, &body).await?;
            println!("environment/{name} configured (updated)");
        }
        None => {
            let body = serde_json::json!({
                "name": name,
                "config": config,
            });
            client.create_environment(&body).await?;
            println!("environment/{name} created");
        }
    }
    Ok(())
}

fn build_environment_config(spec: &manifest::EnvironmentSpec) -> serde_json::Value {
    let mut config = serde_json::Map::new();

    if let Some(ref t) = spec.env_type {
        config.insert("type".into(), serde_json::Value::String(t.clone()));
    }

    if let Some(ref pkgs) = spec.packages {
        let mut packages = serde_json::Map::new();
        if !pkgs.apt.is_empty() {
            packages.insert("apt".into(), serde_json::json!(pkgs.apt));
        }
        if !pkgs.pip.is_empty() {
            packages.insert("pip".into(), serde_json::json!(pkgs.pip));
        }
        if !pkgs.npm.is_empty() {
            packages.insert("npm".into(), serde_json::json!(pkgs.npm));
        }
        if !pkgs.cargo.is_empty() {
            packages.insert("cargo".into(), serde_json::json!(pkgs.cargo));
        }
        if !pkgs.gem.is_empty() {
            packages.insert("gem".into(), serde_json::json!(pkgs.gem));
        }
        if !pkgs.go.is_empty() {
            packages.insert("go".into(), serde_json::json!(pkgs.go));
        }
        config.insert("packages".into(), serde_json::Value::Object(packages));
    }

    if let Some(ref net) = spec.networking {
        let mut networking = serde_json::Map::new();
        if let Some(ref t) = net.net_type {
            networking.insert("type".into(), serde_json::Value::String(t.clone()));
        }
        if !net.allowed_hosts.is_empty() {
            let hosts: Vec<serde_json::Value> = net
                .allowed_hosts
                .iter()
                .map(|h| serde_json::Value::String(h.clone()))
                .collect();
            networking.insert("allowed_hosts".into(), serde_json::Value::Array(hosts));
        }
        if let Some(v) = net.allow_mcp_servers {
            networking.insert("allow_mcp_servers".into(), serde_json::Value::Bool(v));
        }
        if let Some(v) = net.allow_package_managers {
            networking.insert("allow_package_managers".into(), serde_json::Value::Bool(v));
        }
        config.insert("networking".into(), serde_json::Value::Object(networking));
    }

    serde_json::Value::Object(config)
}

async fn apply_task(
    client: &JoysafeterClient,
    manifest: &manifest::TaskManifest,
) -> anyhow::Result<()> {
    let timeout_sec = manifest
        .spec
        .timeout
        .as_deref()
        .map(parse_duration)
        .unwrap_or(7200);

    let mut body = serde_json::json!({
        "agent_name": manifest.spec.agent,
        "prompt": manifest.spec.prompt,
        "system_prompt": manifest.spec.system_prompt,
        "timeout_sec": timeout_sec,
        "max_retries": manifest.spec.max_retries,
    });

    if let Some(ref env_ref) = manifest.spec.environment_ref {
        body["environment_ref"] = serde_json::Value::String(env_ref.clone());
    }

    let resp = client.create_task(&body).await?;
    let id = resp["id"].as_str().unwrap_or("unknown");
    println!("task/{} created (id: {})", manifest.metadata.name, id);
    Ok(())
}

async fn apply_memory_store(
    client: &JoysafeterClient,
    manifest: &manifest::MemoryStoreManifest,
) -> anyhow::Result<()> {
    let name = &manifest.metadata.name;

    let existing = client.list_memory_stores().await?;
    let found = existing.iter().find(|s| s["name"].as_str() == Some(name));

    match found {
        Some(store) => {
            let id = store["id"].as_str().unwrap();
            let mut body = serde_json::json!({ "name": name });
            if let Some(ref desc) = manifest.spec.description {
                body["description"] = serde_json::Value::String(desc.clone());
            }
            if let Some(ref meta) = manifest.spec.metadata {
                body["metadata"] = serde_json::json!(meta);
            }
            client.update_memory_store(id, &body).await?;
            println!("memorystore/{name} configured (updated)");
        }
        None => {
            let mut body = serde_json::json!({ "name": name });
            if let Some(ref desc) = manifest.spec.description {
                body["description"] = serde_json::Value::String(desc.clone());
            }
            if let Some(ref meta) = manifest.spec.metadata {
                body["metadata"] = serde_json::json!(meta);
            }
            client.create_memory_store(&body).await?;
            println!("memorystore/{name} created");
        }
    }
    Ok(())
}
