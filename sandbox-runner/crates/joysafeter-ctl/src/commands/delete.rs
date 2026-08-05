use crate::client::JoysafeterClient;
use crate::DeleteResource;

pub async fn run(client: &JoysafeterClient, resource: &DeleteResource) -> anyhow::Result<()> {
    match resource {
        DeleteResource::Agent { name, force } => {
            let agent = client
                .get_agent_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", name))?;
            let id = agent["id"].as_str().unwrap();
            client.delete_agent(id, *force).await?;
            println!("agent/{} deleted", name);
        }
        DeleteResource::Environment { name } => {
            let env = client
                .get_environment_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Environment '{}' not found", name))?;
            let id = env["id"].as_str().unwrap();
            client.delete_environment(id).await?;
            println!("environment/{} deleted", name);
        }
        DeleteResource::Session { id } => {
            client.delete_session(id).await?;
            println!("session/{} deleted", id);
        }
        DeleteResource::Task { id } => {
            client.cancel_task(id).await?;
            println!("task/{} cancelled", id);
        }
        DeleteResource::MemoryStore { id } => {
            client.delete_memory_store(id).await?;
            println!("memorystore/{} deleted", id);
        }
        DeleteResource::Memory { store, id } => {
            client.delete_memory(store, id).await?;
            println!("memory/{} deleted from store {}", id, store);
        }
        DeleteResource::Secret { name, force } => {
            let secret = client
                .get_secret_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Secret '{}' not found", name))?;
            let id = normalize_resource_id(secret["id"].as_str().unwrap());
            client.delete_secret(id, *force).await?;
            println!("secret/{} deleted", name);
        }
        DeleteResource::Vault { id } => {
            client.delete_vault(id).await?;
            println!("vault/{} deleted", id);
        }
        DeleteResource::VaultCredential { vault, id } => {
            client.delete_vault_credential(vault, id).await?;
            println!("credential/{} deleted from vault {}", id, vault);
        }
    }
    Ok(())
}

fn normalize_resource_id(id: &str) -> &str {
    id.split_once('_').map(|(_, rest)| rest).unwrap_or(id)
}
