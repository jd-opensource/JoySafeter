use async_trait::async_trait;

use crate::ids::SandboxId;

use super::DesiredNetworkPolicy;

#[async_trait]
pub trait NetworkPolicyMaterialResolver: Send + Sync {
    async fn resolve(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy>;
}

#[cfg(test)]
pub struct RejectingNetworkPolicyMaterialResolver;

#[cfg(test)]
#[async_trait]
impl NetworkPolicyMaterialResolver for RejectingNetworkPolicyMaterialResolver {
    async fn resolve(&self, _sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
        anyhow::bail!("network-policy material resolver is not configured")
    }
}
