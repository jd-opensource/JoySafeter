//! Authoritative sandbox-to-node ownership for node-scoped xDS visibility.

use std::collections::HashMap;
use std::sync::{Arc, RwLock};

use tokio::sync::watch;

use crate::ids::SandboxId;

use super::model::ResourceOwner;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum OwnershipTransition {
    Assigned {
        sandbox_id: SandboxId,
        node: String,
    },
    Unchanged {
        sandbox_id: SandboxId,
        node: String,
    },
    Moved {
        sandbox_id: SandboxId,
        previous_node: String,
        new_node: String,
    },
    Removed {
        sandbox_id: SandboxId,
        node: String,
    },
    Missing {
        sandbox_id: SandboxId,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum VisibilityScope {
    Unscoped,
    NodeScoped,
}

struct NodeOwnershipInner {
    scope: VisibilityScope,
    assignments: RwLock<HashMap<SandboxId, String>>,
    revision: watch::Sender<u64>,
}

#[derive(Clone)]
pub struct NodeOwnershipRegistry {
    inner: Arc<NodeOwnershipInner>,
}

impl NodeOwnershipRegistry {
    pub fn unscoped() -> Self {
        Self::new(VisibilityScope::Unscoped)
    }

    pub fn node_scoped() -> Self {
        Self::new(VisibilityScope::NodeScoped)
    }

    fn new(scope: VisibilityScope) -> Self {
        let (revision, _receiver) = watch::channel(0);
        Self {
            inner: Arc::new(NodeOwnershipInner {
                scope,
                assignments: RwLock::new(HashMap::new()),
                revision,
            }),
        }
    }

    pub fn assign(&self, sandbox_id: SandboxId, node: impl Into<String>) -> OwnershipTransition {
        let node = node.into();
        let transition = {
            let mut assignments = self
                .inner
                .assignments
                .write()
                .expect("node ownership registry poisoned");
            match assignments.get(&sandbox_id) {
                Some(existing) if existing == &node => {
                    OwnershipTransition::Unchanged { sandbox_id, node }
                }
                Some(existing) => {
                    let previous_node = existing.clone();
                    assignments.insert(sandbox_id, node.clone());
                    OwnershipTransition::Moved {
                        sandbox_id,
                        previous_node,
                        new_node: node,
                    }
                }
                None => {
                    assignments.insert(sandbox_id, node.clone());
                    OwnershipTransition::Assigned { sandbox_id, node }
                }
            }
        };
        if !matches!(transition, OwnershipTransition::Unchanged { .. }) {
            self.bump_revision();
        }
        transition
    }

    pub fn remove(&self, sandbox_id: SandboxId) -> OwnershipTransition {
        let transition = {
            let mut assignments = self
                .inner
                .assignments
                .write()
                .expect("node ownership registry poisoned");
            match assignments.remove(&sandbox_id) {
                Some(node) => OwnershipTransition::Removed { sandbox_id, node },
                None => OwnershipTransition::Missing { sandbox_id },
            }
        };
        if matches!(transition, OwnershipTransition::Removed { .. }) {
            self.bump_revision();
        }
        transition
    }

    pub fn replace_all(&self, replacement: HashMap<SandboxId, String>) -> Vec<OwnershipTransition> {
        let transitions = {
            let mut assignments = self
                .inner
                .assignments
                .write()
                .expect("node ownership registry poisoned");
            let mut transitions = Vec::new();

            for (sandbox_id, previous_node) in assignments.iter() {
                match replacement.get(sandbox_id) {
                    None => transitions.push(OwnershipTransition::Removed {
                        sandbox_id: *sandbox_id,
                        node: previous_node.clone(),
                    }),
                    Some(new_node) if new_node != previous_node => {
                        transitions.push(OwnershipTransition::Moved {
                            sandbox_id: *sandbox_id,
                            previous_node: previous_node.clone(),
                            new_node: new_node.clone(),
                        });
                    }
                    Some(_) => {}
                }
            }
            for (sandbox_id, node) in &replacement {
                if !assignments.contains_key(sandbox_id) {
                    transitions.push(OwnershipTransition::Assigned {
                        sandbox_id: *sandbox_id,
                        node: node.clone(),
                    });
                }
            }

            transitions.sort_by(|left, right| {
                transition_sandbox_id(left)
                    .as_uuid()
                    .cmp(&transition_sandbox_id(right).as_uuid())
            });
            *assignments = replacement;
            transitions
        };
        if !transitions.is_empty() {
            self.bump_revision();
        }
        transitions
    }

    pub fn owner_node(&self, sandbox_id: SandboxId) -> Option<String> {
        self.inner
            .assignments
            .read()
            .expect("node ownership registry poisoned")
            .get(&sandbox_id)
            .cloned()
    }

    pub fn delivery_owner_node(&self, sandbox_id: SandboxId) -> anyhow::Result<Option<String>> {
        match self.inner.scope {
            VisibilityScope::Unscoped => Ok(None),
            VisibilityScope::NodeScoped => self.owner_node(sandbox_id).map(Some).ok_or_else(|| {
                anyhow::anyhow!("sandbox {sandbox_id} has no authoritative xDS node assignment")
            }),
        }
    }

    pub fn is_visible(&self, owner: ResourceOwner, node: &str) -> bool {
        match owner {
            ResourceOwner::Shared => true,
            ResourceOwner::Sandbox(_) if self.inner.scope == VisibilityScope::Unscoped => true,
            ResourceOwner::Sandbox(sandbox_id) => self
                .inner
                .assignments
                .read()
                .expect("node ownership registry poisoned")
                .get(&sandbox_id)
                .is_some_and(|owner_node| owner_node == node),
        }
    }

    pub fn subscribe(&self) -> watch::Receiver<u64> {
        self.inner.revision.subscribe()
    }

    pub fn current_revision(&self) -> u64 {
        *self.inner.revision.borrow()
    }

    fn bump_revision(&self) {
        self.inner
            .revision
            .send_replace(self.current_revision().saturating_add(1));
    }
}

impl Default for NodeOwnershipRegistry {
    fn default() -> Self {
        Self::unscoped()
    }
}

fn transition_sandbox_id(transition: &OwnershipTransition) -> SandboxId {
    match transition {
        OwnershipTransition::Assigned { sandbox_id, .. }
        | OwnershipTransition::Unchanged { sandbox_id, .. }
        | OwnershipTransition::Moved { sandbox_id, .. }
        | OwnershipTransition::Removed { sandbox_id, .. }
        | OwnershipTransition::Missing { sandbox_id } => *sandbox_id,
    }
}
