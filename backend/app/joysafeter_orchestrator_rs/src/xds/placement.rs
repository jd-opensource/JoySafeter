use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use tracing::{error, warn};

use crate::sandbox::runtime::{PlacementEvent, PlacementEventSink};

use super::control_plane::XdsControlPlane;

#[async_trait]
pub trait PlacementAuthority: Send + Sync {
    async fn apply(&self, event: PlacementEvent) -> anyhow::Result<()>;
}

#[async_trait]
impl PlacementAuthority for XdsControlPlane {
    async fn apply(&self, event: PlacementEvent) -> anyhow::Result<()> {
        match event {
            PlacementEvent::Assigned {
                sandbox_id,
                node_name,
            } => self
                .assign_sandbox_node(sandbox_id, node_name)
                .await
                .map(|_| ()),
            PlacementEvent::Removed { sandbox_id } => {
                self.remove_sandbox_node(sandbox_id).await;
                Ok(())
            }
            PlacementEvent::Reconciled { assignments } => {
                self.replace_node_assignments(assignments).await.map(|_| ())
            }
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub struct PlacementRetryPolicy {
    pub max_attempts: usize,
    pub retry_delay: Duration,
}

impl Default for PlacementRetryPolicy {
    fn default() -> Self {
        Self {
            max_attempts: 3,
            retry_delay: Duration::from_millis(100),
        }
    }
}

#[derive(Clone)]
pub struct PlacementReconcilerHealth {
    degraded: Arc<AtomicBool>,
}

impl PlacementReconcilerHealth {
    pub fn is_degraded(&self) -> bool {
        self.degraded.load(Ordering::Acquire)
    }
}

pub struct PlacementReconciler {
    authority: Arc<dyn PlacementAuthority>,
    receiver: tokio::sync::mpsc::Receiver<PlacementEvent>,
    retry_policy: PlacementRetryPolicy,
    health: PlacementReconcilerHealth,
}

impl PlacementReconciler {
    pub fn new(
        authority: Arc<dyn PlacementAuthority>,
        capacity: usize,
        retry_policy: PlacementRetryPolicy,
    ) -> (PlacementEventSink, Self) {
        assert!(
            retry_policy.max_attempts > 0,
            "placement retry attempts must be positive"
        );
        let (sink, receiver) = PlacementEventSink::channel(capacity);
        let health = PlacementReconcilerHealth {
            degraded: Arc::new(AtomicBool::new(false)),
        };
        (
            sink,
            Self {
                authority,
                receiver,
                retry_policy,
                health,
            },
        )
    }

    pub fn health(&self) -> PlacementReconcilerHealth {
        self.health.clone()
    }

    pub async fn run(mut self) {
        while let Some(event) = self.receiver.recv().await {
            self.apply_with_retry(event).await;
        }
    }

    async fn apply_with_retry(&self, event: PlacementEvent) {
        for attempt in 1..=self.retry_policy.max_attempts {
            match self.authority.apply(event.clone()).await {
                Ok(()) => return,
                Err(error) if attempt < self.retry_policy.max_attempts => {
                    warn!(
                        %error,
                        attempt,
                        max_attempts = self.retry_policy.max_attempts,
                        "placement reconciliation failed; retrying"
                    );
                    tokio::time::sleep(self.retry_policy.retry_delay).await;
                }
                Err(error) => {
                    self.health.degraded.store(true, Ordering::Release);
                    error!(
                        %error,
                        attempts = self.retry_policy.max_attempts,
                        "placement reconciliation exhausted retries"
                    );
                    return;
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::{Arc, Mutex};
    use std::time::Duration;

    use async_trait::async_trait;

    use super::{PlacementAuthority, PlacementReconciler, PlacementRetryPolicy};
    use crate::ids::SandboxId;
    use crate::sandbox::runtime::{PlacementEvent, PlacementEventSendError};

    struct RecordingAuthority {
        failures_remaining: AtomicUsize,
        attempts: AtomicUsize,
        applied: Mutex<Vec<PlacementEvent>>,
    }

    #[async_trait]
    impl PlacementAuthority for RecordingAuthority {
        async fn apply(&self, event: PlacementEvent) -> anyhow::Result<()> {
            self.attempts.fetch_add(1, Ordering::SeqCst);
            if self
                .failures_remaining
                .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |remaining| {
                    remaining.checked_sub(1)
                })
                .is_ok()
            {
                anyhow::bail!("transient ownership failure");
            }
            self.applied.lock().expect("applied lock").push(event);
            Ok(())
        }
    }

    fn policy() -> PlacementRetryPolicy {
        PlacementRetryPolicy {
            max_attempts: 3,
            retry_delay: Duration::from_millis(1),
        }
    }

    #[tokio::test]
    async fn transient_failure_is_retried_without_losing_the_observation() {
        let authority = Arc::new(RecordingAuthority {
            failures_remaining: AtomicUsize::new(2),
            attempts: AtomicUsize::new(0),
            applied: Mutex::new(Vec::new()),
        });
        let (sink, reconciler) = PlacementReconciler::new(authority.clone(), 4, policy());
        let health = reconciler.health();
        let task = tokio::spawn(reconciler.run());
        let sandbox_id = SandboxId::new();

        sink.publish(PlacementEvent::Assigned {
            sandbox_id,
            node_name: "node-a".to_string(),
        })
        .await
        .expect("queue placement");
        drop(sink);
        task.await.expect("reconciler task");

        assert_eq!(authority.attempts.load(Ordering::SeqCst), 3);
        assert!(!health.is_degraded());
        assert!(matches!(
            authority.applied.lock().expect("applied lock").as_slice(),
            [PlacementEvent::Assigned { sandbox_id: applied, node_name }]
                if *applied == sandbox_id && node_name == "node-a"
        ));
    }

    #[tokio::test]
    async fn terminal_failure_is_bounded_and_marks_health_degraded() {
        let authority = Arc::new(RecordingAuthority {
            failures_remaining: AtomicUsize::new(10),
            attempts: AtomicUsize::new(0),
            applied: Mutex::new(Vec::new()),
        });
        let (sink, reconciler) = PlacementReconciler::new(authority.clone(), 2, policy());
        let health = reconciler.health();
        let task = tokio::spawn(reconciler.run());

        sink.publish(PlacementEvent::Removed {
            sandbox_id: SandboxId::new(),
        })
        .await
        .expect("queue placement");
        drop(sink);
        task.await.expect("reconciler task");

        assert_eq!(authority.attempts.load(Ordering::SeqCst), 3);
        assert!(health.is_degraded());
    }

    #[tokio::test]
    async fn relist_replacement_is_delivered_as_one_authoritative_event() {
        let authority = Arc::new(RecordingAuthority {
            failures_remaining: AtomicUsize::new(0),
            attempts: AtomicUsize::new(0),
            applied: Mutex::new(Vec::new()),
        });
        let (sink, reconciler) = PlacementReconciler::new(authority.clone(), 2, policy());
        let task = tokio::spawn(reconciler.run());
        let assignments = HashMap::from([(SandboxId::new(), "node-b".to_string())]);

        sink.publish(PlacementEvent::Reconciled {
            assignments: assignments.clone(),
        })
        .await
        .expect("queue relist");
        drop(sink);
        task.await.expect("reconciler task");

        assert_eq!(
            authority.applied.lock().expect("applied lock").as_slice(),
            &[PlacementEvent::Reconciled { assignments }]
        );
    }

    #[tokio::test]
    async fn placement_queue_reports_backpressure_when_capacity_is_exhausted() {
        let authority = Arc::new(RecordingAuthority {
            failures_remaining: AtomicUsize::new(0),
            attempts: AtomicUsize::new(0),
            applied: Mutex::new(Vec::new()),
        });
        let (sink, _reconciler) = PlacementReconciler::new(authority, 1, policy());

        sink.try_publish(PlacementEvent::Removed {
            sandbox_id: SandboxId::new(),
        })
        .expect("first event fits");
        let error = sink
            .try_publish(PlacementEvent::Removed {
                sandbox_id: SandboxId::new(),
            })
            .expect_err("second event must observe bounded backpressure");

        assert_eq!(error, PlacementEventSendError::Full);
    }
}
