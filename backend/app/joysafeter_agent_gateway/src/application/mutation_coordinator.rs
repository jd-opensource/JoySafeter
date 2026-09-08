use std::collections::HashMap;
use std::sync::{Arc, Mutex as StdMutex, Weak};

use tokio::sync::{Mutex, MutexGuard, OwnedMutexGuard};

use crate::ids::SandboxId;

/// Exact per-sandbox mutation lanes plus the shared recovery gate.
///
/// Operations for one sandbox remain ordered without hashing unrelated
/// sandboxes onto the same lock. Weak entries are periodically reclaimed once
/// no operation or waiter retains the corresponding lane.
const LANE_REGISTRY_SWEEP_THRESHOLD: usize = 65_536;

#[derive(Clone)]
pub struct MutationCoordinator {
    recovery_gate: Arc<Mutex<()>>,
    sandbox_lanes: Arc<StdMutex<HashMap<SandboxId, Weak<Mutex<()>>>>>,
}

impl MutationCoordinator {
    pub fn new(recovery_gate: Arc<Mutex<()>>) -> Self {
        Self {
            recovery_gate,
            sandbox_lanes: Arc::new(StdMutex::new(HashMap::new())),
        }
    }

    pub async fn lock_sandbox(&self, sandbox_id: SandboxId) -> OwnedMutexGuard<()> {
        let lane = {
            let mut lanes = self
                .sandbox_lanes
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            if lanes.len() >= LANE_REGISTRY_SWEEP_THRESHOLD {
                lanes.retain(|_, lane| lane.strong_count() > 0);
            }
            if let Some(lane) = lanes.get(&sandbox_id).and_then(Weak::upgrade) {
                lane
            } else {
                let lane = Arc::new(Mutex::new(()));
                lanes.insert(sandbox_id, Arc::downgrade(&lane));
                lane
            }
        };
        lane.lock_owned().await
    }

    pub async fn lock_recovery(&self) -> MutexGuard<'_, ()> {
        self.recovery_gate.lock().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[tokio::test]
    async fn unrelated_sandboxes_never_share_a_mutation_lane() {
        let coordinator = MutationCoordinator::new(Arc::new(Mutex::new(())));
        let first = SandboxId::new();
        let second = SandboxId::new();
        let _first_guard = coordinator.lock_sandbox(first).await;

        tokio::time::timeout(Duration::from_millis(20), coordinator.lock_sandbox(second))
            .await
            .expect("a different sandbox must have an independent lane");
        assert!(
            tokio::time::timeout(Duration::from_millis(20), coordinator.lock_sandbox(first))
                .await
                .is_err(),
            "the same sandbox must remain serialized"
        );
    }
}
