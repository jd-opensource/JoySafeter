use sqlx::PgPool;

use crate::db::queries;
use crate::ids::SandboxId;
use crate::xds::authority::{MutationAuthorityGuard, RecoveryAuthorityGuard};

use super::envoy_model::validate_egress_policy;
use super::material::NetworkPolicyMaterialResolver;
use super::ports::{
    NetworkPolicyRecoveryEntry, NetworkPolicyRecoveryFailure, NetworkPolicyRuntime,
};

pub async fn recover_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    authority: &RecoveryAuthorityGuard,
) -> anyhow::Result<usize> {
    recover_inventory(pool, runtime, material_resolver, authority).await
}

pub async fn resync_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    authority: &MutationAuthorityGuard,
) -> anyhow::Result<usize> {
    recover_inventory(pool, runtime, material_resolver, authority).await
}

trait InventoryAuthorityGuard {
    fn validate_inventory(&self) -> anyhow::Result<()>;
    fn epoch(&self) -> u64;
}

impl InventoryAuthorityGuard for RecoveryAuthorityGuard {
    fn validate_inventory(&self) -> anyhow::Result<()> {
        self.validate().map_err(Into::into)
    }

    fn epoch(&self) -> u64 {
        RecoveryAuthorityGuard::epoch(self)
    }
}

impl InventoryAuthorityGuard for MutationAuthorityGuard {
    fn validate_inventory(&self) -> anyhow::Result<()> {
        self.validate().map_err(Into::into)
    }

    fn epoch(&self) -> u64 {
        MutationAuthorityGuard::epoch(self)
    }
}

async fn recover_inventory(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    authority: &(impl InventoryAuthorityGuard + Sync),
) -> anyhow::Result<usize> {
    authority.validate_inventory()?;
    let sandboxes = queries::load_recovery_inventory(pool).await?;
    let mut entries = Vec::new();

    for sandbox in sandboxes {
        authority.validate_inventory()?;
        let networking = sandbox
            .config
            .as_ref()
            .and_then(|config| config.get("fingerprint"))
            .and_then(|fingerprint| fingerprint.get("networking"));
        if networking
            .and_then(|value| value.get("type"))
            .and_then(serde_json::Value::as_str)
            != Some("limited")
        {
            quarantine(
                pool,
                sandbox.id,
                sandbox.networking_policy_hash.as_deref(),
                sandbox.networking_policy_version,
                "live sandbox carries network-policy state for a non-limited network mode",
            )
            .await?;
            continue;
        }
        let Some(policy_hash) = sandbox.networking_policy_hash.as_deref() else {
            quarantine(
                pool,
                sandbox.id,
                None,
                sandbox.networking_policy_version,
                "live limited-networking sandbox has no persisted policy hash",
            )
            .await?;
            continue;
        };
        if sandbox.networking_policy_version <= 0 {
            quarantine(
                pool,
                sandbox.id,
                Some(policy_hash),
                sandbox.networking_policy_version,
                "live limited-networking sandbox has no valid persisted policy version",
            )
            .await?;
            continue;
        }

        let desired = match material_resolver.resolve(sandbox.id).await {
            Ok(desired) => desired,
            Err(error) => {
                quarantine(
                    pool,
                    sandbox.id,
                    Some(policy_hash),
                    sandbox.networking_policy_version,
                    &format!("failed to rebuild recovery material: {error:#}"),
                )
                .await?;
                continue;
            }
        };
        if desired.revision().as_str() != policy_hash {
            quarantine(
                pool,
                sandbox.id,
                Some(policy_hash),
                sandbox.networking_policy_version,
                "recovered desired policy does not match durable generation",
            )
            .await?;
            continue;
        }
        let policy = desired.render_for(sandbox.id);
        if let Err(error) = validate_egress_policy(&sandbox.id, &policy) {
            quarantine(
                pool,
                sandbox.id,
                Some(policy_hash),
                sandbox.networking_policy_version,
                &format!("invalid recovered egress policy: {error:#}"),
            )
            .await?;
            continue;
        }
        entries.push(NetworkPolicyRecoveryEntry {
            sandbox_id: sandbox.id,
            generation: super::NetworkPolicyGeneration {
                policy_hash: policy_hash.to_string(),
                policy_version: sandbox.networking_policy_version,
            },
            policy,
        });
    }

    let report = runtime.recover(authority.epoch(), entries).await?;
    authority.validate_inventory()?;
    let mut recovered = 0usize;
    for (sandbox_id, generation) in report.ready {
        authority.validate_inventory()?;
        match queries::mark_generation_applied(pool, sandbox_id, &generation).await? {
            queries::NetworkPolicyAckOutcome::Applied
            | queries::NetworkPolicyAckOutcome::AlreadyReady => recovered += 1,
            queries::NetworkPolicyAckOutcome::Stale => anyhow::bail!(
                "sandbox {sandbox_id} network policy generation changed during recovery"
            ),
            queries::NetworkPolicyAckOutcome::Missing => {}
        }
    }
    for failure in report.failed {
        persist_runtime_failure(pool, failure).await?;
    }
    Ok(recovered)
}

async fn persist_runtime_failure(
    pool: &PgPool,
    failure: NetworkPolicyRecoveryFailure,
) -> anyhow::Result<()> {
    quarantine(
        pool,
        failure.sandbox_id,
        Some(&failure.generation.policy_hash),
        failure.generation.policy_version,
        &failure.reason,
    )
    .await
}

async fn quarantine(
    pool: &PgPool,
    sandbox_id: SandboxId,
    observed_policy_hash: Option<&str>,
    observed_policy_version: i64,
    reason: &str,
) -> anyhow::Result<()> {
    match queries::quarantine_recovery_generation(
        pool,
        sandbox_id,
        observed_policy_hash,
        observed_policy_version,
        reason,
    )
    .await?
    {
        queries::NetworkPolicyFailureOutcome::Recorded
        | queries::NetworkPolicyFailureOutcome::Missing => Ok(()),
        queries::NetworkPolicyFailureOutcome::Stale
        | queries::NetworkPolicyFailureOutcome::AlreadyReady => anyhow::bail!(
            "sandbox {sandbox_id} generation changed while recovery was quarantining it"
        ),
    }
}
