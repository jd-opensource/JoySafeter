use std::sync::Arc;
use std::time::Duration;

use sqlx::PgPool;
use tracing::{debug, error, info, warn};

use super::application::NetworkingReconcileOutcome;
use super::service::NetworkPolicyService;
use crate::db::queries;

pub(crate) struct NetworkPolicyReconciler {
    pool: PgPool,
    service: NetworkPolicyService,
}

impl NetworkPolicyReconciler {
    pub(crate) fn new(pool: PgPool, service: NetworkPolicyService) -> Self {
        Self { pool, service }
    }

    pub(crate) async fn run(self: Arc<Self>) {
        const FAST: Duration = Duration::from_secs(2);
        const IDLE: Duration = Duration::from_secs(15);
        const BATCH: i64 = 20;
        info!("Network policy reconciler started (adaptive 2s/15s)");

        loop {
            let repaired = match self.reconcile_batch(BATCH).await {
                Ok(count) => count,
                Err(error) => {
                    error!(error = %error, "Network policy reconcile failed");
                    0
                }
            };
            tokio::time::sleep(if repaired > 0 { FAST } else { IDLE }).await;
        }
    }

    pub(crate) async fn reconcile_batch(&self, limit: i64) -> anyhow::Result<usize> {
        if !self.service.can_reconcile_as_authority() {
            return Ok(0);
        }
        let degraded = queries::list_degraded_limited_sandboxes(&self.pool, limit).await?;
        if degraded.is_empty() {
            return Ok(0);
        }
        let degraded_count = degraded.len();
        debug!(
            count = degraded_count,
            "Reconciling degraded sandbox networking"
        );

        for sandbox in &degraded {
            match self.service.reconcile_as_authority(sandbox).await {
                Ok(NetworkingReconcileOutcome::Refreshed { policy_hash }) => {
                    info!(
                        sandbox_id = %sandbox.id,
                        policy_hash = %policy_hash,
                        "Reconciled degraded sandbox networking"
                    );
                }
                Ok(_) => {}
                Err(error) => {
                    warn!(
                        sandbox_id = %sandbox.id,
                        error = %error,
                        "Failed to reconcile sandbox networking; will retry next tick"
                    );
                }
            }
        }
        Ok(degraded_count)
    }
}
