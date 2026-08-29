use std::sync::Arc;

use async_trait::async_trait;
use futures::future::BoxFuture;
use std::collections::HashMap;

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

pub type PlacementEventHandler =
    Arc<dyn Fn(PlacementEvent) -> BoxFuture<'static, ()> + Send + Sync>;

#[async_trait]
pub trait SandboxSocketProvisioner: Send + Sync {
    async fn prepare_socket(&self, sandbox_id: SandboxId) -> anyhow::Result<()>;
}
