use std::time::Duration;

use anyhow::Context;
use sqlx::PgPool;

use super::envoy_model::{
    rendered_egress_policy_summary, validate_egress_policy, SandboxCredentials, SandboxEgressPolicy,
};
use super::material::NetworkPolicyMaterialResolver;
use super::ports::{
    NetworkPolicyApplyError, NetworkPolicyApplyRequest, NetworkPolicyRequestQueue,
    NetworkPolicyRuntime,
};
use super::request::NetworkPolicyRequest;
use super::{DesiredNetworkPolicy, NetworkPolicyGeneration};
use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::ids::{SandboxId, SandboxNetworkPolicyId};
use crate::xds::authority::{MutationAuthorityGuard, XdsAuthority};

pub const POLICY_APPLY_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NetworkingReconcileOutcome {
    NotLimited,
    AlreadyReady { policy_hash: String },
    Refreshed { policy_hash: String },
}

pub async fn request_reconcile(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    sandbox: &JoySafeterSandbox,
    queue: Option<&dyn NetworkPolicyRequestQueue>,
    authority: &XdsAuthority,
) -> anyhow::Result<NetworkingReconcileOutcome> {
    let Some(desired) = desired_policy(material_resolver, sandbox).await? else {
        return Ok(NetworkingReconcileOutcome::NotLimited);
    };
    let policy = desired.render_for(sandbox.id);
    validate_egress_policy(&sandbox.id, &policy)?;
    let policy_hash = desired.revision().to_string();
    let prepared = queries::prepare_generation(pool, sandbox.id, &policy_hash).await?;
    if prepared.is_already_ready() {
        return Ok(NetworkingReconcileOutcome::AlreadyReady { policy_hash });
    }
    let generation = prepared.into_generation();

    let outcome = ensure_ready(
        pool,
        runtime,
        material_resolver,
        queue,
        authority,
        sandbox.id,
        &generation,
        POLICY_APPLY_TIMEOUT,
    )
    .await?;
    Ok(match outcome {
        queries::NetworkPolicyAckOutcome::Applied => {
            NetworkingReconcileOutcome::Refreshed { policy_hash }
        }
        queries::NetworkPolicyAckOutcome::AlreadyReady => {
            NetworkingReconcileOutcome::AlreadyReady { policy_hash }
        }
        queries::NetworkPolicyAckOutcome::Stale => anyhow::bail!(
            "sandbox {} network policy generation changed during reconcile",
            sandbox.id
        ),
        queries::NetworkPolicyAckOutcome::Missing => {
            anyhow::bail!("sandbox {} disappeared during reconcile", sandbox.id)
        }
    })
}

pub async fn reconcile_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    sandbox: &JoySafeterSandbox,
    authority: &MutationAuthorityGuard,
) -> anyhow::Result<NetworkingReconcileOutcome> {
    let Some(desired) = desired_policy(material_resolver, sandbox).await? else {
        return Ok(NetworkingReconcileOutcome::NotLimited);
    };
    let policy = desired.render_for(sandbox.id);
    validate_egress_policy(&sandbox.id, &policy)?;
    let policy_hash = desired.revision().to_string();

    let prepared = queries::prepare_generation(pool, sandbox.id, &policy_hash).await?;
    if prepared.is_already_ready() {
        return Ok(NetworkingReconcileOutcome::AlreadyReady { policy_hash });
    }
    let generation = prepared.into_generation();
    apply_generation_as_authority(
        pool,
        runtime,
        material_resolver,
        sandbox.id,
        &generation,
        authority,
    )
    .await
}

pub async fn reconcile_base_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    sandbox: &JoySafeterSandbox,
    authority: &MutationAuthorityGuard,
) -> anyhow::Result<NetworkingReconcileOutcome> {
    let Some(networking) = sandbox_networking(sandbox) else {
        return Ok(NetworkingReconcileOutcome::NotLimited);
    };
    if networking.get("type").and_then(serde_json::Value::as_str) != Some("limited") {
        return Ok(NetworkingReconcileOutcome::NotLimited);
    }

    let desired = material_resolver.resolve_base(sandbox.id).await?;
    let policy_hash = desired.revision().to_string();
    let prepared = queries::prepare_generation(pool, sandbox.id, &policy_hash).await?;
    if prepared.is_already_ready() {
        return Ok(NetworkingReconcileOutcome::AlreadyReady { policy_hash });
    }
    let generation = prepared.into_generation();
    let current = queries::get_sandbox(pool, sandbox.id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("sandbox {} was not found", sandbox.id))?;
    apply_generation_with_desired_as_authority(
        pool,
        runtime,
        current,
        &generation,
        desired,
        authority,
    )
    .await
}

pub async fn apply_generation_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    authority: &MutationAuthorityGuard,
) -> anyhow::Result<NetworkingReconcileOutcome> {
    let sandbox = queries::get_sandbox(pool, sandbox_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("sandbox {sandbox_id} was not found"))?;
    if sandbox.networking_policy_hash.as_deref() != Some(&generation.policy_hash)
        || sandbox.networking_policy_version != generation.policy_version
    {
        anyhow::bail!(
            "stale xDS reconcile request for sandbox {sandbox_id} generation {}",
            generation.policy_version
        );
    }
    if sandbox.networking_status == "ready"
        && sandbox.networking_applied_hash.as_deref() == Some(&generation.policy_hash)
        && sandbox.networking_applied_version == Some(generation.policy_version)
    {
        return Ok(NetworkingReconcileOutcome::AlreadyReady {
            policy_hash: generation.policy_hash.clone(),
        });
    }
    let desired = material_resolver.resolve(sandbox_id).await?;
    apply_generation_with_desired_as_authority(
        pool, runtime, sandbox, generation, desired, authority,
    )
    .await
}

pub async fn apply_generation_with_credentials_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    credentials: SandboxCredentials,
    authority: &MutationAuthorityGuard,
) -> anyhow::Result<NetworkingReconcileOutcome> {
    let sandbox = queries::get_sandbox(pool, sandbox_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("sandbox {sandbox_id} was not found"))?;
    let networking = sandbox_networking(&sandbox);
    let desired = DesiredNetworkPolicy::from_inputs(networking, &credentials)?;
    apply_generation_with_desired_as_authority(
        pool, runtime, sandbox, generation, desired, authority,
    )
    .await
}

async fn apply_generation_with_desired_as_authority(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    sandbox: JoySafeterSandbox,
    generation: &NetworkPolicyGeneration,
    desired: DesiredNetworkPolicy,
    authority: &MutationAuthorityGuard,
) -> anyhow::Result<NetworkingReconcileOutcome> {
    let sandbox_id = sandbox.id;
    if authority.validate().is_err() {
        anyhow::bail!("xDS authority changed before policy application");
    }
    if !matches!(
        sandbox.status.as_str(),
        "creating" | "provisioning" | "idle" | "running"
    ) {
        anyhow::bail!(
            "sandbox {sandbox_id} is not live for xDS reconciliation (status={})",
            sandbox.status
        );
    }
    if sandbox.networking_policy_hash.as_deref() != Some(&generation.policy_hash)
        || sandbox.networking_policy_version != generation.policy_version
    {
        anyhow::bail!(
            "stale xDS reconcile request for sandbox {sandbox_id} generation {}",
            generation.policy_version
        );
    }
    if sandbox.networking_status == "ready"
        && sandbox.networking_applied_hash.as_deref() == Some(&generation.policy_hash)
        && sandbox.networking_applied_version == Some(generation.policy_version)
    {
        return Ok(NetworkingReconcileOutcome::AlreadyReady {
            policy_hash: generation.policy_hash.clone(),
        });
    }
    if sandbox
        .external_id
        .as_deref()
        .filter(|value| !value.is_empty())
        .is_none()
    {
        anyhow::bail!("sandbox {sandbox_id} has no external_id");
    }
    let Some(networking) = sandbox_networking(&sandbox) else {
        return Ok(NetworkingReconcileOutcome::NotLimited);
    };
    if networking.get("type").and_then(serde_json::Value::as_str) != Some("limited") {
        return Ok(NetworkingReconcileOutcome::NotLimited);
    }

    let policy = desired.render_for(sandbox_id);
    validate_egress_policy(&sandbox_id, &policy)?;
    let rendered_summary = rendered_egress_policy_summary(&sandbox_id, &policy);
    let policy_hash = desired.revision().to_string();
    if policy_hash != generation.policy_hash {
        anyhow::bail!("sandbox {sandbox_id} desired policy changed before authority application");
    }

    if let Err(error) = apply_ephemeral(runtime, sandbox_id, generation, policy, authority).await {
        let desired_policy = serde_json::json!({
            "fingerprint": sandbox
                .config
                .as_ref()
                .and_then(|config| config.get("fingerprint"))
                .cloned()
                .unwrap_or_else(|| serde_json::json!({})),
            "networking": networking,
            "recorded_on": "failure",
        });
        let reason = format!("{error:#}");
        let failure_status = classify_failure_status(&error);
        let _ = queries::record_generation_failure(
            pool,
            queries::UpsertNetworkPolicy {
                id: SandboxNetworkPolicyId::new(),
                sandbox_id,
                session_id: sandbox.chat_session_id,
                task_id: None,
                generation,
                desired_policy_json: &desired_policy,
                rendered_summary_json: &rendered_summary,
            },
            failure_status,
            &reason,
        )
        .await;
        return Err(error);
    }
    if authority.validate().is_err() {
        anyhow::bail!("xDS authority changed before policy ACK persistence");
    }
    match queries::mark_generation_applied(pool, sandbox_id, generation).await? {
        queries::NetworkPolicyAckOutcome::Applied => {}
        queries::NetworkPolicyAckOutcome::AlreadyReady => {
            return Ok(NetworkingReconcileOutcome::AlreadyReady { policy_hash });
        }
        queries::NetworkPolicyAckOutcome::Stale => anyhow::bail!(
            "sandbox {sandbox_id} network policy generation changed before ACK persistence"
        ),
        queries::NetworkPolicyAckOutcome::Missing => {
            anyhow::bail!("sandbox {sandbox_id} disappeared before ACK persistence")
        }
    }

    Ok(NetworkingReconcileOutcome::Refreshed { policy_hash })
}

fn classify_failure_status(error: &anyhow::Error) -> queries::NetworkPolicyFailureStatus {
    let envoy_nacked = error
        .chain()
        .any(|cause| cause.downcast_ref::<NetworkPolicyApplyError>().is_some());
    if envoy_nacked {
        queries::NetworkPolicyFailureStatus::Nacked
    } else {
        queries::NetworkPolicyFailureStatus::Failed
    }
}

pub async fn ensure_ready(
    pool: &PgPool,
    runtime: &dyn NetworkPolicyRuntime,
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    queue: Option<&dyn NetworkPolicyRequestQueue>,
    authority: &XdsAuthority,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    timeout: Duration,
) -> anyhow::Result<queries::NetworkPolicyAckOutcome> {
    if let Some(queue) = queue {
        queue
            .publish(NetworkPolicyRequest::reconcile(
                sandbox_id,
                generation.clone(),
            ))
            .await
            .context("failed to request xDS authority reconciliation")?;
        return wait_until_ready(pool, sandbox_id, generation, timeout).await;
    }
    let _application_lock = authority.lock_application().await;
    let guard = authority
        .mutation_guard()
        .ok_or_else(|| anyhow::anyhow!("local xDS authority is not ready"))?;
    match apply_generation_as_authority(
        pool,
        runtime,
        material_resolver,
        sandbox_id,
        generation,
        &guard,
    )
    .await?
    {
        NetworkingReconcileOutcome::Refreshed { .. } => {
            Ok(queries::NetworkPolicyAckOutcome::Applied)
        }
        NetworkingReconcileOutcome::AlreadyReady { .. } => {
            Ok(queries::NetworkPolicyAckOutcome::AlreadyReady)
        }
        NetworkingReconcileOutcome::NotLimited => {
            anyhow::bail!("sandbox {sandbox_id} no longer requires limited networking")
        }
    }
}

pub async fn wait_until_ready(
    pool: &PgPool,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    timeout: Duration,
) -> anyhow::Result<queries::NetworkPolicyAckOutcome> {
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        let sandbox = queries::get_sandbox(pool, sandbox_id)
            .await
            .context("failed to read sandbox network policy state")?
            .ok_or_else(|| {
                anyhow::anyhow!("sandbox {sandbox_id} disappeared while awaiting xDS")
            })?;
        if sandbox.networking_policy_hash.as_deref() != Some(&generation.policy_hash)
            || sandbox.networking_policy_version != generation.policy_version
        {
            anyhow::bail!(
                "sandbox {sandbox_id} network policy generation changed while awaiting xDS authority"
            );
        }
        match sandbox.networking_status.as_str() {
            "ready"
                if sandbox.networking_applied_hash.as_deref() == Some(&generation.policy_hash)
                    && sandbox.networking_applied_version == Some(generation.policy_version) =>
            {
                return Ok(queries::NetworkPolicyAckOutcome::AlreadyReady);
            }
            "nacked" | "failed" => anyhow::bail!(
                "xDS authority rejected sandbox {sandbox_id} policy: {}",
                sandbox
                    .networking_last_error
                    .as_deref()
                    .unwrap_or("unspecified error")
            ),
            _ => {}
        }
        if tokio::time::Instant::now() >= deadline {
            anyhow::bail!(
                "timed out waiting for xDS authority to apply sandbox {sandbox_id} policy generation {}",
                generation.policy_version
            );
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

async fn desired_policy(
    material_resolver: &dyn NetworkPolicyMaterialResolver,
    sandbox: &JoySafeterSandbox,
) -> anyhow::Result<Option<DesiredNetworkPolicy>> {
    if sandbox_networking(sandbox)
        .and_then(|value| value.get("type"))
        .and_then(serde_json::Value::as_str)
        != Some("limited")
    {
        return Ok(None);
    }
    material_resolver.resolve(sandbox.id).await.map(Some)
}

fn sandbox_networking(sandbox: &JoySafeterSandbox) -> Option<&serde_json::Value> {
    sandbox
        .config
        .as_ref()
        .and_then(|config| config.get("fingerprint"))
        .and_then(|fingerprint| fingerprint.get("networking"))
}

pub(crate) async fn apply_ephemeral(
    runtime: &dyn NetworkPolicyRuntime,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    policy: SandboxEgressPolicy,
    authority: &MutationAuthorityGuard,
) -> anyhow::Result<()> {
    if authority.validate().is_err() {
        anyhow::bail!("xDS authority changed before ephemeral policy application");
    }
    validate_egress_policy(&sandbox_id, &policy)?;
    tokio::time::timeout(
        POLICY_APPLY_TIMEOUT,
        runtime.apply(
            NetworkPolicyApplyRequest {
                authority_epoch: authority.epoch(),
                sandbox_id,
                generation: generation.clone(),
            },
            policy,
        ),
    )
    .await
    .unwrap_or_else(|_| {
        Err(anyhow::anyhow!(
            "refresh_networking exceeded {POLICY_APPLY_TIMEOUT:?}"
        ))
    })
}

#[cfg(test)]
#[path = "../../../tests/unit/network_policy/application_test.rs"]
mod tests;
