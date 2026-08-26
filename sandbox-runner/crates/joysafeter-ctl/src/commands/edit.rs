use crate::client::JoysafeterClient;
use crate::editor::open_in_editor;
use crate::EditResource;
use anyhow::Context;
use joysafeter_entity_id::{
    AgentId, CredentialGroupId, CredentialId, EnvironmentId, MemoryStoreId,
};

pub async fn run(client: &JoysafeterClient, resource: &EditResource) -> anyhow::Result<()> {
    match resource {
        EditResource::Agent { name } => edit_agent(client, name).await,
        EditResource::Environment { name } => edit_environment(client, name).await,
        EditResource::Credential { id } => edit_credential(client, id).await,
        EditResource::CredentialGroup { id } => edit_credential_group(client, id).await,
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

    let id = agent["id"]
        .as_str()
        .context("agent response missing id")?
        .parse::<AgentId>()
        .context("agent response contained a non-canonical id")?;
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

    client.update_agent(id, &body).await?;
    println!("agent/{name} edited");
    Ok(())
}

async fn edit_environment(client: &JoysafeterClient, name: &str) -> anyhow::Result<()> {
    let env = client
        .get_environment_by_name(name)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Environment '{}' not found", name))?;

    let id = env["id"]
        .as_str()
        .context("environment response missing id")?
        .parse::<EnvironmentId>()
        .context("environment response contained a non-canonical id")?;

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

    client.update_environment(id, &body).await?;
    println!("environment/{name} edited");
    Ok(())
}

async fn edit_credential(client: &JoysafeterClient, id: &CredentialId) -> anyhow::Result<()> {
    let credential = client.get_credential(*id).await?;
    let skip = [
        "id",
        "kind",
        "provider",
        "protocol",
        "mcp_server_url",
        "group_id",
        "created_at",
        "updated_at",
        "archived_at",
    ];
    let yaml = json_to_editable_yaml(&credential, &skip)?;
    let header = format!(
        "# Editing credential/{id} (save and close to apply, empty file to cancel)\n# Immutable fields are excluded.\n{yaml}"
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
    client.update_credential(*id, &body).await?;
    println!("credential/{id} edited");
    Ok(())
}

async fn edit_credential_group(
    client: &JoysafeterClient,
    id: &CredentialGroupId,
) -> anyhow::Result<()> {
    let group = client.get_credential_group(*id).await?;
    let skip = ["id", "created_at", "updated_at", "archived_at"];
    let yaml = json_to_editable_yaml(&group, &skip)?;
    let header = format!(
        "# Editing credential-group/{id} (save and close to apply, empty file to cancel)\n# Read-only fields are excluded.\n{yaml}"
    );
    let edited = open_in_editor(&header, "resource.yaml")?;
    let stripped = edited
        .lines()
        .filter(|line| !line.starts_with('#'))
        .collect::<Vec<_>>()
        .join("\n");
    if stripped.trim().is_empty() {
        println!("Empty content, edit cancelled.");
        return Ok(());
    }
    let body = serde_yaml::from_str(&stripped).context("Failed to parse edited YAML")?;
    client.update_credential_group(*id, &body).await?;
    println!("credential-group/{id} edited");
    Ok(())
}

async fn edit_memory_store(client: &JoysafeterClient, id: &MemoryStoreId) -> anyhow::Result<()> {
    let store = client.get_memory_store(*id).await?;

    let skip = ["id", "type", "created_at", "updated_at", "archived_at"];
    let yaml = json_to_editable_yaml(&store, &skip)?;
    let id_text = id.to_string();
    let display_name = store["name"].as_str().unwrap_or(&id_text);
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

    client.update_memory_store(*id, &body).await?;
    println!("memory-store/{display_name} edited");
    Ok(())
}
