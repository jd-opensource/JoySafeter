use std::collections::HashMap;

use crate::ids::SandboxId;

use super::model::{NodeId, PlacementRevision};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PlacementChange {
    pub sandbox_id: SandboxId,
    pub previous_node: Option<NodeId>,
    pub current_node: Option<NodeId>,
    pub revision: PlacementRevision,
    pub changed: bool,
}

pub struct NodeRegistry {
    owners: HashMap<SandboxId, NodeId>,
    revision: u64,
    node_aware: bool,
}

impl Default for NodeRegistry {
    fn default() -> Self {
        Self::new(true)
    }
}

impl NodeRegistry {
    pub fn new(node_aware: bool) -> Self {
        Self {
            owners: HashMap::new(),
            revision: 0,
            node_aware,
        }
    }

    pub fn enable_node_aware(&mut self) {
        self.node_aware = true;
    }

    pub fn assign(&mut self, sandbox_id: SandboxId, node_id: NodeId) -> PlacementChange {
        let previous_node = self.owners.get(&sandbox_id).cloned();
        let changed = previous_node.as_ref() != Some(&node_id);
        if changed {
            self.revision = self.revision.saturating_add(1);
            self.owners.insert(sandbox_id, node_id.clone());
        }
        self.node_aware = true;
        PlacementChange {
            sandbox_id,
            previous_node,
            current_node: Some(node_id),
            revision: PlacementRevision::new(self.revision),
            changed,
        }
    }

    pub fn remove(&mut self, sandbox_id: SandboxId) -> Option<PlacementChange> {
        let previous_node = self.owners.remove(&sandbox_id)?;
        self.revision = self.revision.saturating_add(1);
        Some(PlacementChange {
            sandbox_id,
            previous_node: Some(previous_node),
            current_node: None,
            revision: PlacementRevision::new(self.revision),
            changed: true,
        })
    }

    pub fn owner(&self, sandbox_id: SandboxId) -> Option<&NodeId> {
        self.owners.get(&sandbox_id)
    }

    pub fn revision(&self) -> PlacementRevision {
        PlacementRevision::new(self.revision)
    }

    pub fn is_node_aware(&self) -> bool {
        self.node_aware
    }

    pub fn resource_is_visible_to(&self, sandbox_id: Option<SandboxId>, node_id: &NodeId) -> bool {
        let Some(sandbox_id) = sandbox_id else {
            return true;
        };
        match self.owner(sandbox_id) {
            Some(owner) => owner == node_id,
            None => !self.node_aware,
        }
    }
}
