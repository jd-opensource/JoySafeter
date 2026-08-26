use crate::client::JoysafeterClient;
use crate::DeleteResource;
use anyhow::Context;
use joysafeter_entity_id::{AgentId, EnvironmentId};

pub async fn run(client: &JoysafeterClient, resource: &DeleteResource) -> anyhow::Result<()> {
    match resource {
        DeleteResource::Agent { name, force } => {
            let agent = client
                .get_agent_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Agent '{}' not found", name))?;
            let id = agent["id"]
                .as_str()
                .context("agent response missing id")?
                .parse::<AgentId>()
                .context("agent response contained a non-canonical id")?;
            client.delete_agent(id, *force).await?;
            println!("agent/{} deleted", name);
        }
        DeleteResource::Environment { name } => {
            let env = client
                .get_environment_by_name(name)
                .await?
                .ok_or_else(|| anyhow::anyhow!("Environment '{}' not found", name))?;
            let id = env["id"]
                .as_str()
                .context("environment response missing id")?
                .parse::<EnvironmentId>()
                .context("environment response contained a non-canonical id")?;
            client.delete_environment(id).await?;
            println!("environment/{} deleted", name);
        }
        DeleteResource::Session { id } => {
            client.delete_session(*id).await?;
            println!("session/{} deleted", id);
        }
        DeleteResource::Task { id } => {
            client.cancel_task(*id).await?;
            println!("task/{} cancelled", id);
        }
        DeleteResource::MemoryStore { id } => {
            client.delete_memory_store(*id).await?;
            println!("memorystore/{} deleted", id);
        }
        DeleteResource::Memory { store, id } => {
            client.delete_memory(*store, *id).await?;
            println!("memory/{} deleted from store {}", id, store);
        }
        DeleteResource::Credential { id } => {
            client.delete_credential(*id).await?;
            println!("credential/{} deleted", id);
        }
        DeleteResource::CredentialGroup { id } => {
            client.delete_credential_group(*id).await?;
            println!("credential-group/{} deleted", id);
        }
        DeleteResource::CredentialGroupMember { group, id } => {
            client.delete_credential_group_member(*group, *id).await?;
            println!("credential/{} deleted from credential-group {}", id, group);
        }
    }
    Ok(())
}
