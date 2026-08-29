use async_trait::async_trait;
use std::collections::HashMap;
use tokio::sync::mpsc;

use crate::ids::SandboxId;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlacementEvent {
    Assigned {
        sandbox_id: SandboxId,
        node_name: String,
    },
    Removed {
        sandbox_id: SandboxId,
    },
    Reconciled {
        assignments: HashMap<SandboxId, String>,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlacementEventSendError {
    Closed,
    Full,
}

#[derive(Clone)]
pub struct PlacementEventSink {
    sender: mpsc::Sender<PlacementEvent>,
}

impl PlacementEventSink {
    pub(crate) fn channel(capacity: usize) -> (Self, mpsc::Receiver<PlacementEvent>) {
        assert!(capacity > 0, "placement event capacity must be positive");
        let (sender, receiver) = mpsc::channel(capacity);
        (Self { sender }, receiver)
    }

    pub async fn publish(&self, event: PlacementEvent) -> Result<(), PlacementEventSendError> {
        self.sender
            .send(event)
            .await
            .map_err(|_| PlacementEventSendError::Closed)
    }

    pub fn try_publish(&self, event: PlacementEvent) -> Result<(), PlacementEventSendError> {
        self.sender.try_send(event).map_err(|error| match error {
            mpsc::error::TrySendError::Full(_) => PlacementEventSendError::Full,
            mpsc::error::TrySendError::Closed(_) => PlacementEventSendError::Closed,
        })
    }
}

#[async_trait]
pub trait SandboxSocketProvisioner: Send + Sync {
    async fn prepare_socket(&self, sandbox_id: SandboxId) -> anyhow::Result<()>;

    async fn verify_storage(&self) -> anyhow::Result<()> {
        Ok(())
    }
}
