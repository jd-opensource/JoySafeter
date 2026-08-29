//! Authority lifecycle runner independent of the wakeup transport.

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use tracing::{debug, error, info, warn};

use super::authority::{XdsAuthorityGuard, XdsAuthorityState};

const INVENTORY_RECONCILE_INTERVAL: Duration = Duration::from_secs(30);

pub struct AuthorityRequestEnvelope<Request> {
    pub request: Request,
    pub source: String,
}

#[async_trait]
pub trait AuthorityRequestSource<Request>: Send {
    async fn next_batch(&mut self) -> Option<Vec<AuthorityRequestEnvelope<Request>>>;
}

#[async_trait]
pub trait AuthorityWork<Request>: Send + Sync + 'static {
    async fn recover(&self, guard: &XdsAuthorityGuard) -> anyhow::Result<usize>;

    async fn reconcile_inventory(&self, guard: &XdsAuthorityGuard) -> anyhow::Result<usize>;

    async fn apply(&self, request: Request, guard: &XdsAuthorityGuard) -> anyhow::Result<()>;
}

pub async fn run_authority_worker<Request: Send + 'static>(
    mut source: Box<dyn AuthorityRequestSource<Request>>,
    work: Arc<dyn AuthorityWork<Request>>,
    authority: XdsAuthorityState,
) {
    let mut recovered_epoch = None;
    let mut last_inventory_reconcile = None;

    info!("xDS authority worker started");

    loop {
        if let Some(guard) = authority.advertised_guard() {
            if recovered_epoch != Some(guard.epoch()) {
                let _application_lock = authority.lock_application().await;
                match work.recover(&guard).await {
                    Ok(recovered) if authority.mark_ready(&guard) => {
                        recovered_epoch = Some(guard.epoch());
                        last_inventory_reconcile = Some(tokio::time::Instant::now());
                        info!(
                            epoch = guard.epoch(),
                            recovered, "xDS authority recovery completed"
                        );
                    }
                    Ok(_) => {
                        recovered_epoch = None;
                        warn!(
                            epoch = guard.epoch(),
                            "xDS authority changed during recovery"
                        );
                    }
                    Err(error) => {
                        recovered_epoch = None;
                        error!(epoch = guard.epoch(), error = %error, "xDS authority recovery failed; will retry");
                    }
                }
            }
        } else {
            recovered_epoch = None;
            last_inventory_reconcile = None;
        }

        if let Some(guard) = authority.ready_guard() {
            let elapsed = last_inventory_reconcile
                .map(|last| last.elapsed())
                .unwrap_or(INVENTORY_RECONCILE_INTERVAL);
            if should_reconcile_inventory(recovered_epoch, guard.epoch(), elapsed) {
                let _application_lock = authority.lock_application().await;
                match work.reconcile_inventory(&guard).await {
                    Ok(removed) => {
                        last_inventory_reconcile = Some(tokio::time::Instant::now());
                        if removed > 0 {
                            info!(removed, "Pruned stale xDS sandbox networking");
                        }
                    }
                    Err(error) => {
                        warn!(epoch = guard.epoch(), error = %error, "xDS authority inventory reconcile failed; will retry");
                    }
                }
            }
        }

        let Some(entries) = source.next_batch().await else {
            continue;
        };

        for envelope in entries {
            let Some(guard) = authority.ready_guard() else {
                continue;
            };
            debug!(source = %envelope.source, epoch = guard.epoch(), "Received authority work request");
            let work = work.clone();
            let authority = authority.clone();
            tokio::spawn(async move {
                let _application_lock = authority.lock_application().await;
                if let Err(error) = work.apply(envelope.request, &guard).await {
                    debug!(epoch = guard.epoch(), error = %error, "Authority work request skipped or failed");
                }
            });
        }
    }
}

fn should_reconcile_inventory(
    recovered_epoch: Option<u64>,
    current_epoch: u64,
    elapsed: Duration,
) -> bool {
    recovered_epoch == Some(current_epoch) && elapsed >= INVENTORY_RECONCILE_INTERVAL
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn inventory_reconcile_requires_current_recovered_epoch_and_interval() {
        assert!(!should_reconcile_inventory(
            Some(7),
            7,
            Duration::from_secs(29)
        ));
        assert!(should_reconcile_inventory(
            Some(7),
            7,
            Duration::from_secs(30)
        ));
        assert!(!should_reconcile_inventory(
            Some(6),
            7,
            Duration::from_secs(30)
        ));
    }
}
