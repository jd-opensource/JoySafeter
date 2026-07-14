use crate::client::JoysafeterClient;
use crate::editor::open_in_editor;
use crate::EditResource;
use anyhow::Context;

pub async fn run(client: &JoysafeterClient, resource: &EditResource) -> anyhow::Result<()> {
    match resource {
        EditResource::Agent { name } => edit_agent(client, name).await,
        EditResource::Environment { name } => edit_environment(client, name).await,
        EditResource::Secret { name } => edit_secret(client, name).await,
        EditResource::MemoryStore { id } => edit_memory_store(client, id).await,
    }
}

fn json_to_editable_yaml(val: &serde_json::Value, skip_keys: &[&str]) -> anyhow::Result<String> {
    let mut map = val
        .as_object()
        .ok_or_else(|| anyhow::anyhow!("Expected JSON object"))?
        .clone();
    for key in skip_keys {
        map.remove(*key);
    }
    let clean = serde_json::Value::Object(map);
    serde_yaml::to_string(&clean).context("Failed to serialize to YAML")
}

async fn edit_agent(client: &JoysafeterClient, name: &str) -> anyhow::Result<()> {
    let agent = client
        .get_agent_by_name(name)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", name))?;

    let id = agent["id"].as_str().unwrap().to_string();
    let version = agent["version"].as_i64();

    let skip = ["id", "created_at", "updated_at", "archived_at", "version"];
    let yaml = json_to_editable_yaml(&agent, &skip)?;
    let header = format!(
        "# Editing agent/{name} (save and close to apply, empty file to cancel)\n# Read-only fields (id, version, created_at) are excluded.\n{yaml}"
    );

    let edited = open_in_editor(&header, "resource.yaml")?;
    let stripped: String = edited
        .lines()
        .filter(|l| !l.starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n");

    if stripped.trim().is_empty() {
        println!("Empty content, edit cancelled.");
        return Ok(());
    }

    let mut body: serde_json::Value =
        serde_yaml::from_str(&stripped).context("Failed to parse edited YAML")?;

    if let Some(v) = version {
        body["version"] = serde_json::Value::Number(v.into());
    }

    // Rename "system" field alias if user wrote "system_prompt"
    if let Some(sp) = body.as_object_mut().and_then(|m| m.remove("system_prompt")) {
        body["system"] = sp;
    }

    client.update_agent(&id, &body).await?;
    println!("agent/{name} edited");
    Ok(())
}

async fn edit_environment(client: &JoysafeterClient, name: &str) -> anyhow::Result<()> {
    let env = client
        .get_environment_by_name(name)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Environment '{}' not found", name))?;

    let id = env["id"].as_str().unwrap().to_string();

    let skip = ["id", "name", "created_at", "updated_at", "archived_at"];
    let yaml = json_to_editable_yaml(&env, &skip)?;
    let header = format!(
        "# Editing environment/{name} (save and close to apply, empty file to cancel)\n# Read-only fields (id, name, created_at) are excluded.\n{yaml}"
    );

    let edited = open_in_editor(&header, "resource.yaml")?;
    let stripped: String = edited
        .lines()
        .filter(|l| !l.starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n");

    if stripped.trim().is_empty() {
        println!("Empty content, edit cancelled.");
        return Ok(());
    }

    let body: serde_json::Value =
        serde_yaml::from_str(&stripped).context("Failed to parse edited YAML")?;

    client.update_environment(&id, &body).await?;
    println!("environment/{name} edited");
    Ok(())
}

async fn edit_secret(client: &JoysafeterClient, name: &str) -> anyhow::Result<()> {
    let secret = client
        .get_secret_by_name(name)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Secret '{}' not found", name))?;

    let id = secret["id"].as_str().unwrap().to_string();

    let keys = secret["keys"]
        .as_array()
        .map(|arr| arr.iter().filter_map(|v| v.as_str()).collect::<Vec<_>>())
        .unwrap_or_default();

    let mut data = serde_json::Map::new();
    for key in &keys {
        data.insert(key.to_string(), serde_json::Value::String("".to_string()));
    }
    let scaffold = serde_json::json!({ "data": data });
    let yaml = serde_yaml::to_string(&scaffold).context("Failed to serialize")?;
    let header = format!(
        "# Editing secret/{name} (save and close to apply, empty file to cancel)\n# Fill in new values for each key. Empty values are kept unchanged.\n# Existing keys: {}\n{yaml}",
        keys.join(", ")
    );

    let edited = open_in_editor(&header, "resource.yaml")?;
    let stripped: String = edited
        .lines()
        .filter(|l| !l.starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n");

    if stripped.trim().is_empty() {
        println!("Empty content, edit cancelled.");
        return Ok(());
    }

    let parsed: serde_json::Value =
        serde_yaml::from_str(&stripped).context("Failed to parse edited YAML")?;

    let new_data = parsed
        .get("data")
        .and_then(|d| d.as_object())
        .ok_or_else(|| anyhow::anyhow!("Expected 'data' object in edited YAML"))?;

    let mut filtered = serde_json::Map::new();
    for (k, v) in new_data {
        if let Some(s) = v.as_str() {
            if !s.is_empty() {
                filtered.insert(k.clone(), v.clone());
            }
        } else {
            filtered.insert(k.clone(), v.clone());
        }
    }

    if filtered.is_empty() {
        println!("No values changed, edit cancelled.");
        return Ok(());
    }

    let body = serde_json::json!({ "data": filtered });
    client.update_secret(&id, &body).await?;
    println!("secret/{name} edited ({} key(s) updated)", filtered.len());
    Ok(())
}

async fn edit_memory_store(client: &JoysafeterClient, id: &str) -> anyhow::Result<()> {
    let store = client.get_memory_store(id).await?;

    let skip = ["id", "type", "created_at", "updated_at", "archived_at"];
    let yaml = json_to_editable_yaml(&store, &skip)?;
    let display_name = store["name"].as_str().unwrap_or(id);
    let header = format!(
        "# Editing memory-store/{display_name} (save and close to apply, empty file to cancel)\n# Read-only fields (id, created_at, updated_at) are excluded.\n{yaml}"
    );

    let edited = open_in_editor(&header, "resource.yaml")?;
    let stripped: String = edited
        .lines()
        .filter(|l| !l.starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n");

    if stripped.trim().is_empty() {
        println!("Empty content, edit cancelled.");
        return Ok(());
    }

    let body: serde_json::Value =
        serde_yaml::from_str(&stripped).context("Failed to parse edited YAML")?;

    client.update_memory_store(id, &body).await?;
    println!("memory-store/{display_name} edited");
    Ok(())
}
