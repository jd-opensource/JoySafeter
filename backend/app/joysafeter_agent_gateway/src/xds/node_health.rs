//! Stream-fenced Envoy node readiness derived from current CDS/LDS ACK state.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, RwLock};

use super::delivery::NodeSessionId;
use super::model::ResourceType;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnvoyNodeStatus {
    pub node_id: String,
    pub connected: bool,
    pub ready: bool,
}

#[derive(Debug, Clone)]
struct NodeHealth {
    session: NodeSessionId,
    connected: bool,
    ready: bool,
    acknowledged_types: HashSet<ResourceType>,
    pending_nonces: HashMap<ResourceType, String>,
}

impl NodeHealth {
    fn connected(session: NodeSessionId) -> Self {
        Self {
            session,
            connected: true,
            ready: false,
            acknowledged_types: HashSet::new(),
            pending_nonces: HashMap::new(),
        }
    }

    fn refresh_readiness(&mut self) -> bool {
        let was_ready = self.ready;
        self.ready = self.connected
            && self.pending_nonces.is_empty()
            && [ResourceType::Cluster, ResourceType::Listener]
                .iter()
                .all(|resource_type| self.acknowledged_types.contains(resource_type));
        self.ready && !was_ready
    }
}

#[derive(Clone, Default)]
pub struct EnvoyNodeHealthRegistry {
    nodes: Arc<RwLock<HashMap<String, NodeHealth>>>,
}

impl EnvoyNodeHealthRegistry {
    pub fn connect(&self, node: &str, session: NodeSessionId) {
        self.write_nodes()
            .insert(node.to_string(), NodeHealth::connected(session));
    }

    pub fn mark_pending(
        &self,
        node: &str,
        session: NodeSessionId,
        resource_type: ResourceType,
        nonce: &str,
    ) {
        let mut nodes = self.write_nodes();
        let Some(health) = nodes
            .get_mut(node)
            .filter(|health| health.session == session)
        else {
            return;
        };
        health.acknowledged_types.remove(&resource_type);
        health
            .pending_nonces
            .insert(resource_type, nonce.to_string());
        health.ready = false;
    }

    pub fn acknowledge(
        &self,
        node: &str,
        session: NodeSessionId,
        resource_type: ResourceType,
        nonce: &str,
    ) -> bool {
        let mut nodes = self.write_nodes();
        let Some(health) = nodes
            .get_mut(node)
            .filter(|health| health.session == session)
        else {
            return false;
        };
        if health
            .pending_nonces
            .get(&resource_type)
            .map(String::as_str)
            != Some(nonce)
        {
            return false;
        }
        health.pending_nonces.remove(&resource_type);
        health.acknowledged_types.insert(resource_type);
        health.refresh_readiness()
    }

    pub fn reject(
        &self,
        node: &str,
        session: NodeSessionId,
        resource_type: ResourceType,
        nonce: &str,
    ) {
        let mut nodes = self.write_nodes();
        let Some(health) = nodes
            .get_mut(node)
            .filter(|health| health.session == session)
        else {
            return;
        };
        if health
            .pending_nonces
            .get(&resource_type)
            .map(String::as_str)
            != Some(nonce)
        {
            return;
        }
        health.pending_nonces.remove(&resource_type);
        health.acknowledged_types.remove(&resource_type);
        health.ready = false;
    }

    pub fn disconnect(&self, node: &str, session: NodeSessionId) -> bool {
        let mut nodes = self.write_nodes();
        let Some(health) = nodes
            .get_mut(node)
            .filter(|health| health.session == session)
        else {
            return false;
        };
        health.connected = false;
        health.ready = false;
        health.pending_nonces.clear();
        true
    }

    pub fn retain_connected_or_assigned(&self, assigned_nodes: &HashSet<String>) {
        self.write_nodes()
            .retain(|node, health| health.connected || assigned_nodes.contains(node));
    }

    pub fn snapshot(&self) -> Vec<EnvoyNodeStatus> {
        let mut snapshot = self
            .read_nodes()
            .iter()
            .map(|(node_id, health)| EnvoyNodeStatus {
                node_id: node_id.clone(),
                connected: health.connected,
                ready: health.ready,
            })
            .collect::<Vec<_>>();
        snapshot.sort_by(|left, right| left.node_id.cmp(&right.node_id));
        snapshot
    }

    fn read_nodes(&self) -> std::sync::RwLockReadGuard<'_, HashMap<String, NodeHealth>> {
        self.nodes
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn write_nodes(&self) -> std::sync::RwLockWriteGuard<'_, HashMap<String, NodeHealth>> {
        self.nodes
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

#[cfg(test)]
#[path = "../../tests/unit/xds/node_health_test.rs"]
mod tests;
