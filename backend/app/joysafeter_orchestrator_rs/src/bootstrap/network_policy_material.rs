use std::sync::Arc;

use sqlx::PgPool;

use crate::db::queries;
use crate::ids::SandboxId;
use crate::kernel::credentials::runtime_projection::rebuild_sandbox_credentials;
use crate::kernel::network_policy::material::NetworkPolicyMaterialResolver;
use crate::kernel::network_policy::DesiredNetworkPolicy;

pub(crate) fn build_network_policy_material_resolver(
    pool: PgPool,
    llm_egress_allowed_hosts: Vec<String>,
) -> Arc<dyn NetworkPolicyMaterialResolver> {
    Arc::new(PostgresNetworkPolicyMaterialResolver {
        pool,
        llm_egress_allowed_hosts,
    })
}

#[derive(Clone)]
struct PostgresNetworkPolicyMaterialResolver {
    pool: PgPool,
    llm_egress_allowed_hosts: Vec<String>,
}

#[async_trait::async_trait]
impl NetworkPolicyMaterialResolver for PostgresNetworkPolicyMaterialResolver {
    async fn resolve(&self, sandbox_id: SandboxId) -> anyhow::Result<DesiredNetworkPolicy> {
        let sandbox = queries::get_sandbox(&self.pool, sandbox_id)
            .await?
            .ok_or_else(|| anyhow::anyhow!("sandbox {sandbox_id} was not found"))?;
        let networking = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("fingerprint"))
            .and_then(|fingerprint| fingerprint.get("networking"));
        let credentials =
            rebuild_sandbox_credentials(&self.pool, &sandbox, &self.llm_egress_allowed_hosts)
                .await?;
        DesiredNetworkPolicy::from_inputs(networking, &credentials)
    }
}
