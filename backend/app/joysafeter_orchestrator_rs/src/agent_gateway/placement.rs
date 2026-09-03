use std::sync::Arc;

use async_trait::async_trait;
use joysafeter_agent_gateway_contract::{
    AssignSandboxPlacementRequest, ReconcilePlacementsRequest, SandboxPlacement,
};

use crate::sandbox::runtime::PlacementEvent;
use crate::xds::placement::PlacementAuthority;

use super::AgentGatewayApi;

pub struct AgentGatewayPlacementAuthority {
    client: Arc<dyn AgentGatewayApi>,
}

impl AgentGatewayPlacementAuthority {
    pub fn new(client: Arc<dyn AgentGatewayApi>) -> Self {
        Self { client }
    }
}

#[async_trait]
impl PlacementAuthority for AgentGatewayPlacementAuthority {
    async fn apply(&self, event: PlacementEvent) -> anyhow::Result<()> {
        match event {
            PlacementEvent::Assigned {
                sandbox_id,
                node_name,
            } => {
                self.client
                    .assign_placement(
                        sandbox_id,
                        AssignSandboxPlacementRequest { node_id: node_name },
                    )
                    .await
            }
            PlacementEvent::Removed { sandbox_id } => {
                self.client.remove_placement(sandbox_id).await
            }
            PlacementEvent::Reconciled { assignments } => {
                let mut assignments = assignments
                    .into_iter()
                    .map(|(sandbox_id, node_id)| SandboxPlacement {
                        sandbox_id: sandbox_id.to_string(),
                        node_id,
                    })
                    .collect::<Vec<_>>();
                assignments.sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));
                self.client
                    .reconcile_placements(ReconcilePlacementsRequest { assignments })
                    .await
            }
        }
    }
}
