//! Shared sandbox destruction protocol.
//!
//! Destroying a sandbox safely under concurrency is a claim → destroy → finalize
//! dance: first CAS-claim the DB row into `stopping` (so a concurrent
//! attach/restart cannot race the provider call), then destroy the provider
//! runtime, then finalize the DB row to `destroyed`. If the provider call fails
//! (for a reason other than "already gone"), the claim must be rolled back so a
//! later sweep can retry.
//!
//! This protocol previously lived in three near-identical copies across
//! [`crate::kernel::sandbox_resolver`] and [`crate::kernel::sandbox_controller`].
//! Because the copies encode concurrent-mutation safety, any drift between them
//! is a data race. They now share this single implementation; only the *claim*
//! step (which varies by call site) stays at the call site.

use std::sync::Arc;

use async_trait::async_trait;
use sqlx::PgPool;
use tracing::warn;

use crate::db::queries;
use crate::ids::SandboxId;
use crate::kernel::network_policy::service::NetworkPolicyService;
use crate::sandbox::provider::SandboxProvider;

#[async_trait]
pub(crate) trait SandboxNetworkCleanup: Send + Sync {
    async fn teardown_networking(&self, sandbox_id: SandboxId) -> anyhow::Result<()>;
}

#[async_trait]
impl SandboxNetworkCleanup for NetworkPolicyService {
    async fn teardown_networking(&self, sandbox_id: SandboxId) -> anyhow::Result<()> {
        self.teardown(sandbox_id).await.map(|_| ())
    }
}

fn provider_runtime_is_absent(message: &str) -> bool {
    message.contains("No such container") || message.contains("404")
}

pub(crate) async fn destroy_unpersisted_sandbox(
    provider: &Arc<dyn SandboxProvider>,
    network_cleanup: &dyn SandboxNetworkCleanup,
    sandbox_id: SandboxId,
    external_id: &str,
    reason: &str,
) -> anyhow::Result<()> {
    let destroy_error = provider
        .destroy(external_id)
        .await
        .err()
        .map(|error| error.to_string())
        .filter(|message| !provider_runtime_is_absent(message));
    let networking_error = network_cleanup
        .teardown_networking(sandbox_id)
        .await
        .err()
        .map(|error| error.to_string());

    match (destroy_error, networking_error) {
        (None, None) => Ok(()),
        (Some(destroy_error), None) => {
            anyhow::bail!("failed to destroy unpersisted sandbox {sandbox_id} during {reason}: {destroy_error}")
        }
        (None, Some(networking_error)) => {
            anyhow::bail!("failed to tear down networking for unpersisted sandbox {sandbox_id} during {reason}: {networking_error}")
        }
        (Some(destroy_error), Some(networking_error)) => anyhow::bail!(
            "failed to clean up unpersisted sandbox {sandbox_id} during {reason}: provider destroy failed: {destroy_error}; networking teardown failed: {networking_error}"
        ),
    }
}

/// Finalize a sandbox destroy after the caller has already CAS-claimed the row
/// into `stopping`.
///
/// Steps:
/// 1. Destroy the provider runtime (no-op when `external_id` is `None`).
///    "No such container" / 404 is treated as success (already gone).
/// 2. On any other provider error: restore the DB row to `restore_status` (undo
///    the claim) and return the error so the caller/sweeper can retry.
/// 3. Finalize the DB row `stopping -> destroyed`; on success, tear down
///    networking. If the finalize CAS misses (row changed underneath), log and
///    return `false`.
///
/// Returns `Ok(true)` when the row was finalized to `destroyed`, `Ok(false)`
/// when the finalize was skipped because the row changed.
///
/// `restore_status` is the status the row held *before* the caller claimed it —
/// the value to roll back to on provider failure.
pub(crate) async fn finalize_claimed_sandbox_destroy(
    pool: &PgPool,
    provider: &Arc<dyn SandboxProvider>,
    network_cleanup: &dyn SandboxNetworkCleanup,
    sandbox_id: SandboxId,
    external_id: Option<&str>,
    restore_status: &str,
    reason: &str,
) -> anyhow::Result<bool> {
    if let Some(ext_id) = external_id {
        if let Err(err) = provider.destroy(ext_id).await {
            let message = err.to_string();
            if !provider_runtime_is_absent(&message) {
                let _ = queries::restore_sandbox_after_passive_destroy_failure(
                    pool,
                    sandbox_id,
                    restore_status,
                    external_id,
                )
                .await;
                anyhow::bail!("failed to destroy sandbox {sandbox_id} during {reason}: {message}");
            }
        }
    }

    let destroyed = queries::destroy_sandbox_if_status_and_external_id(
        pool,
        sandbox_id,
        "stopping",
        external_id,
    )
    .await?;
    if destroyed {
        let _ = network_cleanup.teardown_networking(sandbox_id).await;
    } else {
        warn!(
            sandbox_id = %sandbox_id,
            reason,
            "Provider destroy completed but DB finalize skipped because sandbox row changed"
        );
    }

    Ok(destroyed)
}

/// Claim a sandbox with the standard passive-destroy CAS (status + external_id
/// match, no active tasks), then run the shared destroy/finalize protocol.
///
/// This is the common path used by the controller sweeps and resolver cleanup
/// where the expected status is known. Returns `Ok(false)` (without touching the
/// provider) if the claim misses because the row changed first.
pub(crate) async fn destroy_observed_sandbox(
    pool: &PgPool,
    provider: &Arc<dyn SandboxProvider>,
    network_cleanup: &dyn SandboxNetworkCleanup,
    sandbox_id: SandboxId,
    observed_status: &str,
    external_id: Option<&str>,
    reason: &str,
) -> anyhow::Result<bool> {
    let claimed =
        queries::claim_sandbox_for_passive_destroy(pool, sandbox_id, observed_status, external_id)
            .await?;

    if !claimed {
        warn!(
            sandbox_id = %sandbox_id,
            status = %observed_status,
            reason,
            "Skipped passive sandbox destroy because DB row changed before provider call"
        );
        return Ok(false);
    }

    finalize_claimed_sandbox_destroy(
        pool,
        provider,
        network_cleanup,
        sandbox_id,
        external_id,
        observed_status,
        reason,
    )
    .await
}
