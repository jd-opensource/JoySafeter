//! Authority lifecycle runner independent of the wakeup transport.

use std::collections::VecDeque;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use tracing::{debug, error, info, warn};

use super::authority::{
    AuthorityPhase, MutationAuthorityGuard, RecoveryAuthorityGuard, XdsAuthority,
};

const INVENTORY_RECONCILE_INTERVAL: Duration = Duration::from_secs(30);
const MAX_FOREGROUND_AUTHORITY_TASKS: usize = 32;
const MAX_PENDING_AUTHORITY_REQUESTS: usize = 1024;

pub struct AuthorityRequestEnvelope<Request> {
    pub request: Request,
    pub source: String,
    pub coalescing_key: Option<String>,
}

#[async_trait]
pub trait AuthorityRequestSource<Request>: Send {
    async fn next_batch(&mut self) -> Option<Vec<AuthorityRequestEnvelope<Request>>>;
}

#[async_trait]
pub trait AuthorityWork<Request>: Send + Sync + 'static {
    async fn recover(&self, guard: &RecoveryAuthorityGuard) -> anyhow::Result<usize>;

    async fn reconcile_inventory(&self, guard: &MutationAuthorityGuard) -> anyhow::Result<usize>;

    async fn apply(&self, request: Request, guard: &MutationAuthorityGuard) -> anyhow::Result<()>;
}

pub async fn run_authority_worker<Request: Send + 'static>(
    source: Box<dyn AuthorityRequestSource<Request>>,
    work: Arc<dyn AuthorityWork<Request>>,
    authority: XdsAuthority,
) {
    run_authority_worker_with_interval(source, work, authority, INVENTORY_RECONCILE_INTERVAL).await;
}

async fn run_authority_worker_with_interval<Request: Send + 'static>(
    mut source: Box<dyn AuthorityRequestSource<Request>>,
    work: Arc<dyn AuthorityWork<Request>>,
    authority: XdsAuthority,
    inventory_reconcile_interval: Duration,
) {
    let mut recovered_epoch = None;
    let mut last_inventory_reconcile = None;
    let mut inventory_reconcile_task: Option<tokio::task::JoinHandle<()>> = None;
    let mut foreground_tasks = tokio::task::JoinSet::new();
    let mut pending_requests: VecDeque<AuthorityRequestEnvelope<Request>> = VecDeque::new();

    info!("xDS authority worker started");

    loop {
        if let Some(guard) = authority.recovery_guard() {
            if recovered_epoch != Some(guard.epoch()) {
                let _application_lock = authority.lock_application().await;
                match work.recover(&guard).await {
                    Ok(recovered) => {
                        if matches!(authority.phase(), AuthorityPhase::Staging { .. })
                            && authority.begin_recovery_serving(&guard).is_err()
                        {
                            recovered_epoch = None;
                            warn!(
                                epoch = guard.epoch(),
                                "xDS authority changed before recovery serving"
                            );
                            continue;
                        }
                        if authority.mark_ready(&guard).is_err() {
                            recovered_epoch = None;
                            warn!(
                                epoch = guard.epoch(),
                                "xDS authority changed during recovery"
                            );
                            continue;
                        }
                        recovered_epoch = Some(guard.epoch());
                        last_inventory_reconcile = Some(tokio::time::Instant::now());
                        info!(
                            epoch = guard.epoch(),
                            recovered, "xDS authority recovery completed"
                        );
                    }
                    Err(error) => {
                        recovered_epoch = None;
                        error!(epoch = guard.epoch(), error = %error, "xDS authority recovery failed; will retry");
                    }
                }
            }
        } else if !matches!(authority.phase(), AuthorityPhase::Ready { .. }) {
            recovered_epoch = None;
            last_inventory_reconcile = None;
            pending_requests.clear();
            foreground_tasks.abort_all();
            while foreground_tasks.try_join_next().is_some() {}
            if let Some(task) = inventory_reconcile_task.take() {
                task.abort();
            }
        }

        if inventory_reconcile_task
            .as_ref()
            .is_some_and(|task| task.is_finished())
        {
            if let Some(task) = inventory_reconcile_task.take() {
                if let Err(error) = task.await {
                    warn!(%error, "xDS authority inventory reconcile task failed");
                }
            }
        }

        if let Some(guard) = authority.mutation_guard() {
            let elapsed = last_inventory_reconcile
                .map(|last| last.elapsed())
                .unwrap_or(inventory_reconcile_interval);
            if should_reconcile_inventory_after(
                recovered_epoch,
                guard.epoch(),
                elapsed,
                inventory_reconcile_interval,
            ) && inventory_reconcile_task.is_none()
            {
                last_inventory_reconcile = Some(tokio::time::Instant::now());
                let work = work.clone();
                inventory_reconcile_task = Some(tokio::spawn(async move {
                    if let Err(error) = guard.validate() {
                        debug!(epoch = guard.epoch(), %error, "Skipped stale xDS authority inventory reconcile");
                        return;
                    }
                    match work.reconcile_inventory(&guard).await {
                        Ok(removed) => {
                            if removed > 0 {
                                info!(removed, "Pruned stale xDS sandbox networking");
                            }
                        }
                        Err(error) => {
                            warn!(epoch = guard.epoch(), error = %error, "xDS authority inventory reconcile failed; will retry after interval");
                        }
                    }
                }));
            }
        }

        while foreground_tasks.len() < MAX_FOREGROUND_AUTHORITY_TASKS {
            let Some(envelope) = pending_requests.pop_front() else {
                break;
            };
            let Some(guard) = authority.mutation_guard() else {
                pending_requests.clear();
                break;
            };
            debug!(source = %envelope.source, epoch = guard.epoch(), "Received authority work request");
            let work = work.clone();
            foreground_tasks.spawn(async move {
                if let Err(error) = work.apply(envelope.request, &guard).await {
                    warn!(epoch = guard.epoch(), error = %error, "Authority work request skipped or failed");
                }
            });
        }

        if !pending_requests.is_empty() && foreground_tasks.len() >= MAX_FOREGROUND_AUTHORITY_TASKS
        {
            let _ = foreground_tasks.join_next().await;
            continue;
        }

        if foreground_tasks.is_empty() {
            if let Some(entries) = source.next_batch().await {
                let dropped = enqueue_coalesced(&mut pending_requests, entries);
                if dropped > 0 {
                    warn!(
                        dropped,
                        "Dropped oldest xDS authority wakeups after pending queue reached capacity"
                    );
                }
            }
            continue;
        }

        tokio::select! {
            result = foreground_tasks.join_next() => {
                if let Some(Err(error)) = result {
                    warn!(%error, "xDS authority foreground task failed");
                }
            }
            entries = source.next_batch() => {
                if let Some(entries) = entries {
                    let dropped = enqueue_coalesced(&mut pending_requests, entries);
                    if dropped > 0 {
                        warn!(dropped, "Dropped oldest xDS authority wakeups after pending queue reached capacity");
                    }
                }
            }
        }
    }
}

fn enqueue_coalesced<Request>(
    pending: &mut VecDeque<AuthorityRequestEnvelope<Request>>,
    entries: Vec<AuthorityRequestEnvelope<Request>>,
) -> usize {
    let mut dropped = 0;
    for envelope in entries {
        if let Some(key) = envelope.coalescing_key.as_deref() {
            pending.retain(|queued| queued.coalescing_key.as_deref() != Some(key));
        }
        pending.push_back(envelope);
        while pending.len() > MAX_PENDING_AUTHORITY_REQUESTS {
            pending.pop_front();
            dropped += 1;
        }
    }
    dropped
}

#[cfg(test)]
fn should_reconcile_inventory(
    recovered_epoch: Option<u64>,
    current_epoch: u64,
    elapsed: Duration,
) -> bool {
    should_reconcile_inventory_after(
        recovered_epoch,
        current_epoch,
        elapsed,
        INVENTORY_RECONCILE_INTERVAL,
    )
}

fn should_reconcile_inventory_after(
    recovered_epoch: Option<u64>,
    current_epoch: u64,
    elapsed: Duration,
    interval: Duration,
) -> bool {
    recovered_epoch == Some(current_epoch) && elapsed >= interval
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;
    use tokio::sync::{mpsc, Notify, Semaphore};

    struct PollingSource {
        receiver: mpsc::UnboundedReceiver<()>,
    }

    #[async_trait]
    impl AuthorityRequestSource<()> for PollingSource {
        async fn next_batch(&mut self) -> Option<Vec<AuthorityRequestEnvelope<()>>> {
            match self.receiver.try_recv() {
                Ok(request) => Some(vec![AuthorityRequestEnvelope {
                    request,
                    source: "test".to_string(),
                    coalescing_key: None,
                }]),
                Err(mpsc::error::TryRecvError::Empty) => {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                    None
                }
                Err(mpsc::error::TryRecvError::Disconnected) => None,
            }
        }
    }

    struct BlockingInventoryWork {
        inventory_started: Notify,
        release_inventory: Notify,
        apply_started: Notify,
    }

    #[async_trait]
    impl AuthorityWork<()> for BlockingInventoryWork {
        async fn recover(&self, _guard: &RecoveryAuthorityGuard) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn reconcile_inventory(
            &self,
            guard: &MutationAuthorityGuard,
        ) -> anyhow::Result<usize> {
            let _application_lock = guard.lock_application().await;
            self.inventory_started.notify_one();
            self.release_inventory.notified().await;
            Ok(0)
        }

        async fn apply(&self, _request: (), guard: &MutationAuthorityGuard) -> anyhow::Result<()> {
            let _application_lock = guard.lock_application().await;
            self.apply_started.notify_one();
            Ok(())
        }
    }

    struct FailingInventoryWork {
        inventory_attempts: AtomicUsize,
        first_attempt: Notify,
    }

    struct BlockingForegroundWork {
        first_started: Notify,
        release_first: Notify,
        second_started: Notify,
    }

    struct BoundedForegroundWork {
        active: AtomicUsize,
        max_active: AtomicUsize,
        release: Semaphore,
    }

    struct U8PollingSource {
        receiver: mpsc::UnboundedReceiver<u8>,
    }

    #[async_trait]
    impl AuthorityRequestSource<u8> for U8PollingSource {
        async fn next_batch(&mut self) -> Option<Vec<AuthorityRequestEnvelope<u8>>> {
            match self.receiver.try_recv() {
                Ok(request) => Some(vec![AuthorityRequestEnvelope {
                    request,
                    source: "test".to_string(),
                    coalescing_key: None,
                }]),
                Err(mpsc::error::TryRecvError::Empty) => {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                    None
                }
                Err(mpsc::error::TryRecvError::Disconnected) => None,
            }
        }
    }

    #[async_trait]
    impl AuthorityWork<u8> for BlockingForegroundWork {
        async fn recover(&self, _guard: &RecoveryAuthorityGuard) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn reconcile_inventory(
            &self,
            _guard: &MutationAuthorityGuard,
        ) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn apply(&self, request: u8, _guard: &MutationAuthorityGuard) -> anyhow::Result<()> {
            match request {
                1 => {
                    self.first_started.notify_one();
                    self.release_first.notified().await;
                }
                2 => self.second_started.notify_one(),
                _ => {}
            }
            Ok(())
        }
    }

    #[async_trait]
    impl AuthorityWork<u8> for BoundedForegroundWork {
        async fn recover(&self, _guard: &RecoveryAuthorityGuard) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn reconcile_inventory(
            &self,
            _guard: &MutationAuthorityGuard,
        ) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn apply(&self, _request: u8, _guard: &MutationAuthorityGuard) -> anyhow::Result<()> {
            let active = self.active.fetch_add(1, Ordering::SeqCst) + 1;
            self.max_active.fetch_max(active, Ordering::SeqCst);
            let permit = self.release.acquire().await.expect("release semaphore");
            permit.forget();
            self.active.fetch_sub(1, Ordering::SeqCst);
            Ok(())
        }
    }

    #[test]
    fn pending_authority_requests_coalesce_by_key() {
        let mut pending = VecDeque::from([
            AuthorityRequestEnvelope {
                request: 1_u8,
                source: "first-a".to_string(),
                coalescing_key: Some("sandbox-a".to_string()),
            },
            AuthorityRequestEnvelope {
                request: 2_u8,
                source: "first-b".to_string(),
                coalescing_key: Some("sandbox-b".to_string()),
            },
        ]);

        let dropped = enqueue_coalesced(
            &mut pending,
            vec![AuthorityRequestEnvelope {
                request: 3_u8,
                source: "latest-a".to_string(),
                coalescing_key: Some("sandbox-a".to_string()),
            }],
        );

        assert_eq!(dropped, 0);
        assert_eq!(pending.len(), 2);
        assert_eq!(pending.pop_front().expect("sandbox-b request").request, 2);
        assert_eq!(
            pending
                .pop_front()
                .expect("latest sandbox-a request")
                .request,
            3
        );
    }

    #[test]
    fn pending_authority_requests_drop_oldest_after_capacity() {
        let mut pending = VecDeque::new();
        let entries = (0..=MAX_PENDING_AUTHORITY_REQUESTS)
            .map(|request| AuthorityRequestEnvelope {
                request,
                source: "capacity-test".to_string(),
                coalescing_key: Some(format!("sandbox-{request}")),
            })
            .collect();

        let dropped = enqueue_coalesced(&mut pending, entries);

        assert_eq!(dropped, 1);
        assert_eq!(pending.len(), MAX_PENDING_AUTHORITY_REQUESTS);
        assert_eq!(pending.front().expect("oldest retained request").request, 1);
    }

    #[tokio::test]
    async fn foreground_authority_work_has_a_hard_concurrency_limit() {
        let authority = XdsAuthority::managed();
        let recovery = authority.begin_staging().expect("begin authority recovery");
        authority
            .begin_recovery_serving(&recovery)
            .expect("begin recovery serving");
        authority
            .mark_ready(&recovery)
            .expect("mark authority ready");
        let (sender, receiver) = mpsc::unbounded_channel();
        let work = Arc::new(BoundedForegroundWork {
            active: AtomicUsize::new(0),
            max_active: AtomicUsize::new(0),
            release: Semaphore::new(0),
        });
        let worker = tokio::spawn(run_authority_worker_with_interval(
            Box::new(U8PollingSource { receiver }),
            work.clone(),
            authority,
            Duration::from_secs(60),
        ));

        for request in 0..40 {
            sender.send(request).expect("queue authority request");
        }
        tokio::time::timeout(Duration::from_secs(1), async {
            while work.active.load(Ordering::SeqCst) < MAX_FOREGROUND_AUTHORITY_TASKS {
                tokio::time::sleep(Duration::from_millis(1)).await;
            }
        })
        .await
        .expect("authority worker should fill its bounded foreground capacity");
        tokio::time::sleep(Duration::from_millis(20)).await;
        assert_eq!(
            work.max_active.load(Ordering::SeqCst),
            MAX_FOREGROUND_AUTHORITY_TASKS
        );

        work.release.add_permits(40);
        worker.abort();
    }

    #[async_trait]
    impl AuthorityWork<()> for FailingInventoryWork {
        async fn recover(&self, _guard: &RecoveryAuthorityGuard) -> anyhow::Result<usize> {
            Ok(0)
        }

        async fn reconcile_inventory(
            &self,
            _guard: &MutationAuthorityGuard,
        ) -> anyhow::Result<usize> {
            self.inventory_attempts.fetch_add(1, Ordering::SeqCst);
            self.first_attempt.notify_one();
            anyhow::bail!("synthetic stale removal timeout")
        }

        async fn apply(&self, _request: (), _guard: &MutationAuthorityGuard) -> anyhow::Result<()> {
            Ok(())
        }
    }

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

    #[tokio::test]
    async fn inventory_reconcile_is_serialized_with_foreground_apply() {
        let authority = XdsAuthority::managed();
        authority.begin_staging().expect("begin authority recovery");
        let (sender, receiver) = mpsc::unbounded_channel();
        let work = Arc::new(BlockingInventoryWork {
            inventory_started: Notify::new(),
            release_inventory: Notify::new(),
            apply_started: Notify::new(),
        });
        let worker = tokio::spawn(run_authority_worker_with_interval(
            Box::new(PollingSource { receiver }),
            work.clone(),
            authority,
            Duration::from_millis(10),
        ));

        tokio::time::timeout(
            Duration::from_millis(200),
            work.inventory_started.notified(),
        )
        .await
        .expect("inventory reconcile should start");
        sender.send(()).expect("queue foreground request");
        assert!(
            tokio::time::timeout(Duration::from_millis(40), work.apply_started.notified())
                .await
                .is_err(),
            "foreground apply must not overtake an inventory mutation based on an older DB snapshot"
        );

        work.release_inventory.notify_one();
        tokio::time::timeout(Duration::from_millis(100), work.apply_started.notified())
            .await
            .expect("foreground apply should proceed after inventory publication completes");
        worker.abort();
    }

    #[tokio::test]
    async fn failed_inventory_reconcile_respects_retry_interval() {
        let authority = XdsAuthority::managed();
        authority.begin_staging().expect("begin authority recovery");
        let (_sender, receiver) = mpsc::unbounded_channel();
        let work = Arc::new(FailingInventoryWork {
            inventory_attempts: AtomicUsize::new(0),
            first_attempt: Notify::new(),
        });
        let worker = tokio::spawn(run_authority_worker_with_interval(
            Box::new(PollingSource { receiver }),
            work.clone(),
            authority,
            Duration::from_millis(100),
        ));

        tokio::time::timeout(Duration::from_millis(250), work.first_attempt.notified())
            .await
            .expect("inventory reconcile should run");
        tokio::time::sleep(Duration::from_millis(40)).await;
        assert_eq!(work.inventory_attempts.load(Ordering::SeqCst), 1);

        worker.abort();
    }

    #[tokio::test]
    async fn slow_foreground_work_does_not_block_later_requests_at_worker_layer() {
        let authority = XdsAuthority::managed();
        let recovery = authority.begin_staging().expect("begin authority recovery");
        authority
            .begin_recovery_serving(&recovery)
            .expect("begin recovery serving");
        authority
            .mark_ready(&recovery)
            .expect("mark authority ready");
        let (sender, receiver) = mpsc::unbounded_channel();
        let work = Arc::new(BlockingForegroundWork {
            first_started: Notify::new(),
            release_first: Notify::new(),
            second_started: Notify::new(),
        });
        let worker = tokio::spawn(run_authority_worker_with_interval(
            Box::new(U8PollingSource { receiver }),
            work.clone(),
            authority,
            Duration::from_secs(60),
        ));

        sender.send(1).expect("queue first request");
        tokio::time::timeout(Duration::from_millis(200), work.first_started.notified())
            .await
            .expect("first request should start");
        sender.send(2).expect("queue second request");

        tokio::time::timeout(Duration::from_millis(100), work.second_started.notified())
            .await
            .expect("slow delivery settlement must not block later authority work");

        work.release_first.notify_one();
        worker.abort();
    }
}
