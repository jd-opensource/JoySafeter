use std::collections::HashSet;

use anyhow::Context;
use sqlx::PgPool;

use crate::db::queries;
use crate::xds::authority::XdsAuthorityGuard;

use super::material::NetworkPolicyMaterialResolver;
use super::ports::NetworkPolicyRuntime;

pub async fn recover_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    authority: &XdsAuthorityGuard,
) -> anyhow::Result<usize> {
    if !authority.is_current() {
        anyhow::bail!("xDS authority changed before network-policy recovery started");
    }

    runtime.prune(&HashSet::new()).await?;
    let sandboxes = queries::list_live_sandboxes_for_recovery(pool).await?;
    let mut recovered = 0usize;

    for sandbox in &sandboxes {
        let networking = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("fingerprint"))
            .and_then(|fingerprint| fingerprint.get("networking"));
        if networking
            .and_then(|value| value.get("type"))
            .and_then(|value| value.as_str())
            != Some("limited")
        {
            continue;
        }
        if !authority.is_current() {
            anyhow::bail!("xDS authority changed during network-policy recovery");
        }

        let desired = material_resolver.resolve(sandbox.id).await?;
        let policy_hash = sandbox
            .networking_policy_hash
            .clone()
            .unwrap_or_else(|| desired.revision().to_string());
        if desired.revision().as_str() != policy_hash {
            anyhow::bail!(
                "sandbox {} recovery policy hash does not match durable generation",
                sandbox.id
            );
        }
        let generation =
            queries::reopen_network_policy_for_authority_recovery(pool, sandbox.id, &policy_hash)
                .await?;

        runtime
            .apply(sandbox.id, desired.render_for(sandbox.id))
            .await
            .with_context(|| format!("failed to recover network policy for {}", sandbox.id))?;
        if !authority.is_current() {
            anyhow::bail!("xDS authority changed before recovery ACK persistence");
        }
        match queries::mark_sandbox_network_policy_acked(pool, sandbox.id, &generation).await? {
            queries::NetworkPolicyAckOutcome::Applied
            | queries::NetworkPolicyAckOutcome::AlreadyReady => recovered += 1,
            queries::NetworkPolicyAckOutcome::Stale => anyhow::bail!(
                "sandbox {} network policy generation changed during recovery",
                sandbox.id
            ),
            queries::NetworkPolicyAckOutcome::Missing => anyhow::bail!(
                "sandbox {} disappeared during network-policy recovery",
                sandbox.id
            ),
        }
    }

    Ok(recovered)
}
