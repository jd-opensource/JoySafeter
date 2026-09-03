use async_trait::async_trait;

use crate::ids::SandboxId;

use super::DesiredNetworkPolicy;

#[async_trait]
pub trait NetworkPolicyMaterialResolver: Send + Sync {
    async fn resolve(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy>;

    /// Resolve the durable policy without task-scoped Agent Identity material.
    ///
    /// Cleanup must keep the identity lease persisted until Envoy has ACKed the
    /// replacement policy. Implementations backed by durable state therefore
    /// need an explicit way to ignore that still-present lease while compiling
    /// the base policy.
    async fn resolve_base(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
        self.resolve(sandbox_id).await
    }
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
