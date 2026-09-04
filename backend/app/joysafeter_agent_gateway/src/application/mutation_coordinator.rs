use std::sync::Arc;

use tokio::sync::{Mutex, MutexGuard};

use crate::ids::SandboxId;

/// A bounded set of per-sandbox mutation lanes plus the shared recovery gate.
///
/// Operations for one sandbox must remain ordered, while an Envoy ACK wait for
/// one sandbox must never stop unrelated sandboxes from publishing. A fixed
/// number of lanes keeps memory bounded; UUID v7 random tail bytes distribute
/// concurrently active sandboxes across the lanes.
///
/// Sized well above the realistic count of *concurrently mutating* sandboxes so
/// two unrelated sandboxes rarely share a lane (and thus rarely serialize behind
/// each other's bounded Envoy ACK wait). Each lane is a zero-payload `Mutex`
/// (~tens of bytes), so a few thousand lanes cost only kilobytes. The in-lane ACK
/// wait itself is already bounded by `delivery_timeout`. (H2)
const SANDBOX_MUTATION_LANES: usize = 4099;

#[derive(Clone)]
pub struct MutationCoordinator {
    recovery_gate: Arc<Mutex<()>>,
    sandbox_lanes: Arc<[Mutex<()>]>,
}

impl MutationCoordinator {
    pub fn new(recovery_gate: Arc<Mutex<()>>) -> Self {
        let sandbox_lanes = (0..SANDBOX_MUTATION_LANES)
            .map(|_| Mutex::new(()))
            .collect::<Vec<_>>()
            .into();
        Self {
            recovery_gate,
            sandbox_lanes,
        }
    }

    pub async fn lock_sandbox(&self, sandbox_id: SandboxId) -> MutexGuard<'_, ()> {
        self.sandbox_lanes[self.lane(sandbox_id)].lock().await
    }

    pub async fn lock_recovery(&self) -> MutexGuard<'_, ()> {
        self.recovery_gate.lock().await
    }

    fn lane(&self, sandbox_id: SandboxId) -> usize {
        let uuid = sandbox_id.as_uuid();
        let bytes = uuid.as_bytes();
        let random_tail = u64::from_le_bytes(
            bytes[8..16]
                .try_into()
                .expect("a UUID always contains sixteen bytes"),
        );
        random_tail as usize % self.sandbox_lanes.len()
    }
}
