use std::time::Duration;

use anyhow::Context;
use sqlx::PgPool;

use super::envoy_model::{
    rendered_egress_policy_summary, validate_egress_policy, SandboxCredentials, SandboxEgressPolicy,
};
use super::error::NetworkPolicyApplyError;
use super::material::NetworkPolicyMaterialResolver;
use super::ports::{NetworkPolicyApplyRequest, NetworkPolicyRequestQueue, NetworkPolicyRuntime};
use super::request::NetworkPolicyRequest;
use super::{DesiredNetworkPolicy, NetworkPolicyGeneration};
use crate::db::models::JoySafeterSandbox;
use crate::db::queries;
use crate::ids::{SandboxId, SandboxNetworkPolicyId};
use crate::xds::authority::{MutationAuthorityGuard, XdsAuthority};

/// Total budget for a single network-policy apply (`prepare` + `publish` +
/// `settle`).
///
/// This MUST stay strictly greater than the inner `settle` delivery timeout
/// (`EnvoyPolicyConfig::delivery_timeout`, derived from
/// `JOYSAFETER_ENVOY_SOCKET_READY_TIMEOUT_MS`, default 30s) plus the publish
/// budget (sandbox lock ≤5s + xDS submit ≤10s). If the two collide, this outer
/// timeout always fires first and masks a delivery/ACK stall as the generic
/// `apply_timeout` instead of the actionable `delivery_timeout`. 60s leaves
/// headroom above the 30s default so delivery stalls surface with their real
/// code.
pub const POLICY_APPLY_TIMEOUT: Duration = Duration::from_secs(60);

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
    let rendered_summary = rendered_egress_policy_summary(&sandbox_id, &policy);
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
    let policy_hash = desired.revision().to_string();
    if policy_hash != generation.policy_hash {
        anyhow::bail!("sandbox {sandbox_id} desired policy changed before authority application");
    }

    let request = NetworkPolicyApplyRequest {
        authority_epoch: authority.epoch(),
        sandbox_id,
        generation: generation.clone(),
    };
    let application = async {
        authority
            .validate()
            .map_err(|_| NetworkPolicyApplyError::AuthorityChanged)?;
        validate_egress_policy(&sandbox_id, &policy)
            .map_err(|error| NetworkPolicyApplyError::InvalidPolicy(format!("{error:#}")))?;
        runtime.prepare_apply(&request, &policy).await?;
        let ticket = {
            let _application_lock = authority.lock_application().await;
            authority
                .validate()
                .map_err(|_| NetworkPolicyApplyError::AuthorityChanged)?;
            let current = queries::get_sandbox(pool, sandbox_id)
                .await
                .map_err(|error| NetworkPolicyApplyError::StateReadFailed(format!("{error:#}")))?
                .ok_or_else(|| {
                    NetworkPolicyApplyError::SandboxUnavailable(format!(
                        "sandbox {sandbox_id} was not found"
                    ))
                })?;
            if !matches!(
                current.status.as_str(),
                "creating" | "provisioning" | "idle" | "running"
            ) {
                return Err(NetworkPolicyApplyError::SandboxUnavailable(format!(
                    "sandbox {sandbox_id} is not live for xDS publication (status={})",
                    current.status
                )));
            }
            if current.networking_policy_hash.as_deref() != Some(&generation.policy_hash)
                || current.networking_policy_version != generation.policy_version
            {
                return Err(NetworkPolicyApplyError::GenerationSuperseded);
            }
            runtime.publish_apply(request, policy).await?
        };
        runtime.settle_apply(ticket).await
    };
    if let Err(error) = tokio::time::timeout(POLICY_APPLY_TIMEOUT, application)
        .await
        .unwrap_or(Err(NetworkPolicyApplyError::ApplyTimedOut))
    {
        persist_apply_failure(
            pool,
            &sandbox,
            generation,
            &desired_policy,
            &rendered_summary,
            &error,
        )
        .await?;
        return Err(error.into());
    }
    if authority.validate().is_err() {
        let error = NetworkPolicyApplyError::AuthorityChanged;
        persist_apply_failure(
            pool,
            &sandbox,
            generation,
            &desired_policy,
            &rendered_summary,
            &error,
        )
        .await?;
        return Err(error.into());
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
            "nacked" => anyhow::bail!(
                "xDS authority rejected sandbox {sandbox_id} policy: {}",
                sandbox
                    .networking_last_error
                    .as_deref()
                    .unwrap_or("unspecified error")
            ),
            "failed" => anyhow::bail!(
                "network policy application failed for sandbox {sandbox_id} (code={}, retryable={}): {}",
                sandbox
                    .networking_last_error_code
                    .as_deref()
                    .unwrap_or("unknown"),
                sandbox.networking_retryable,
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

async fn persist_apply_failure(
    pool: &PgPool,
    sandbox: &JoySafeterSandbox,
    generation: &NetworkPolicyGeneration,
    desired_policy: &serde_json::Value,
    rendered_summary: &serde_json::Value,
    error: &NetworkPolicyApplyError,
) -> anyhow::Result<()> {
    let Some(persistence) = error.persistence() else {
        return Ok(());
    };
    let reason = error.to_string();
    queries::record_generation_failure(
        pool,
        queries::UpsertNetworkPolicy {
            id: SandboxNetworkPolicyId::new(),
            sandbox_id: sandbox.id,
            session_id: sandbox.chat_session_id,
            task_id: None,
            generation,
            desired_policy_json: desired_policy,
            rendered_summary_json: rendered_summary,
        },
        queries::NetworkPolicyFailureRecord {
            status: persistence.status,
            code: error.code(),
            retryable: persistence.retryable,
            message: &reason,
            nack_reason: persistence.nack_reason,
        },
    )
    .await
    .with_context(|| {
        format!(
            "failed to persist network-policy failure {} for sandbox {}",
            error.code(),
            sandbox.id
        )
    })?;
    Ok(())
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
    let request = NetworkPolicyApplyRequest {
        authority_epoch: authority.epoch(),
        sandbox_id,
        generation: generation.clone(),
    };
    let result = tokio::time::timeout(POLICY_APPLY_TIMEOUT, async {
        validate_egress_policy(&sandbox_id, &policy)
            .map_err(|error| NetworkPolicyApplyError::InvalidPolicy(format!("{error:#}")))?;
        runtime.prepare_apply(&request, &policy).await?;
        let ticket = {
            let _application_lock = authority.lock_application().await;
            authority
                .validate()
                .map_err(|_| NetworkPolicyApplyError::AuthorityChanged)?;
            runtime.publish_apply(request, policy).await?
        };
        runtime.settle_apply(ticket).await
    })
    .await
    .unwrap_or(Err(NetworkPolicyApplyError::ApplyTimedOut));
    result.map_err(Into::into)
}

#[cfg(test)]
mod apply_timeout_tests {
    use super::POLICY_APPLY_TIMEOUT;
    use std::time::Duration;

    /// The outer apply budget must exceed the inner settle delivery timeout
    /// (`JOYSAFETER_ENVOY_SOCKET_READY_TIMEOUT_MS`, default 30s) plus the publish
    /// budget (sandbox lock <=5s + xDS submit <=10s). Otherwise the outer timeout
    /// fires first and masks a delivery/ACK stall as `apply_timeout` instead of
    /// the actionable `delivery_timeout`.
    #[test]
    fn apply_timeout_exceeds_default_delivery_budget() {
        let default_delivery_timeout = Duration::from_secs(30);
        let publish_budget = Duration::from_secs(15);
        assert!(
            POLICY_APPLY_TIMEOUT > default_delivery_timeout + publish_budget,
            "POLICY_APPLY_TIMEOUT ({POLICY_APPLY_TIMEOUT:?}) must exceed the default \
             delivery timeout plus publish budget so delivery stalls surface as \
             delivery_timeout, not apply_timeout"
        );
    }
}
