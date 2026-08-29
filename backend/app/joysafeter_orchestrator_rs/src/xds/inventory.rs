use std::collections::{BTreeMap, BTreeSet, HashSet};

use prost_types::Any;

use crate::ids::SandboxId;

use super::model::ResourceType;

#[derive(Clone, Debug, PartialEq)]
pub struct XdsResource {
    sandbox_id: Option<SandboxId>,
    resource_type: ResourceType,
    name: String,
    payload: Any,
}

impl XdsResource {
    pub fn new(
        sandbox_id: SandboxId,
        resource_type: ResourceType,
        name: impl Into<String>,
        payload: Any,
    ) -> Self {
        Self {
            sandbox_id: Some(sandbox_id),
            resource_type,
            name: name.into(),
            payload,
        }
    }

    pub fn shared(resource_type: ResourceType, name: impl Into<String>, payload: Any) -> Self {
        Self {
            sandbox_id: None,
            resource_type,
            name: name.into(),
            payload,
        }
    }

    pub fn sandbox_id(&self) -> Option<SandboxId> {
        self.sandbox_id
    }

    pub fn resource_type(&self) -> ResourceType {
        self.resource_type
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn payload(&self) -> &Any {
        &self.payload
    }
}

#[derive(Clone, Debug, PartialEq)]
pub enum InventoryMutation {
    Upsert(XdsResource),
    Remove {
        sandbox_id: Option<SandboxId>,
        resource_type: ResourceType,
        name: String,
    },
}

impl InventoryMutation {
    pub fn upsert(resource: XdsResource) -> Self {
        Self::Upsert(resource)
    }

    pub fn remove(
        sandbox_id: Option<SandboxId>,
        resource_type: ResourceType,
        name: impl Into<String>,
    ) -> Self {
        Self::Remove {
            sandbox_id,
            resource_type,
            name: name.into(),
        }
    }

    pub fn sandbox_id(&self) -> Option<SandboxId> {
        match self {
            Self::Upsert(resource) => resource.sandbox_id(),
            Self::Remove { sandbox_id, .. } => *sandbox_id,
        }
    }

    pub fn resource_type(&self) -> ResourceType {
        match self {
            Self::Upsert(resource) => resource.resource_type(),
            Self::Remove { resource_type, .. } => *resource_type,
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Self::Upsert(resource) => resource.name(),
            Self::Remove { name, .. } => name,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct VersionedResourceChange {
    version: u64,
    resource_type: ResourceType,
    mutations: Vec<InventoryMutation>,
}

impl VersionedResourceChange {
    pub fn new(
        version: u64,
        resource_type: ResourceType,
        mutations: Vec<InventoryMutation>,
    ) -> Self {
        Self {
            version,
            resource_type,
            mutations,
        }
    }

    pub fn version(&self) -> u64 {
        self.version
    }

    pub fn resource_type(&self) -> ResourceType {
        self.resource_type
    }

    pub fn mutations(&self) -> &[InventoryMutation] {
        &self.mutations
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct InventoryApplyResult {
    version: u64,
    changed_types: BTreeMap<SandboxId, BTreeSet<ResourceType>>,
}

impl InventoryApplyResult {
    pub fn version(&self) -> u64 {
        self.version
    }

    pub fn changed_types_for(&self, sandbox_id: SandboxId) -> BTreeSet<ResourceType> {
        self.changed_types
            .get(&sandbox_id)
            .cloned()
            .unwrap_or_default()
    }
}

pub struct ResourceInventory {
    resources: BTreeMap<(ResourceType, String), XdsResource>,
    version: u64,
    change_log: Vec<VersionedResourceChange>,
    change_log_limit: usize,
}

impl Default for ResourceInventory {
    fn default() -> Self {
        Self::new(4096)
    }
}

impl ResourceInventory {
    pub fn new(change_log_limit: usize) -> Self {
        Self {
            resources: BTreeMap::new(),
            version: 0,
            change_log: Vec::new(),
            change_log_limit,
        }
    }

    pub fn upsert(&mut self, resource: XdsResource) -> Option<XdsResource> {
        self.resources.insert(
            (resource.resource_type(), resource.name().to_string()),
            resource,
        )
    }

    pub fn remove(&mut self, resource_type: ResourceType, name: &str) -> Option<XdsResource> {
        self.resources.remove(&(resource_type, name.to_string()))
    }

    pub fn for_sandbox(&self, sandbox_id: SandboxId) -> Vec<XdsResource> {
        self.resources
            .values()
            .filter(|resource| resource.sandbox_id() == Some(sandbox_id))
            .cloned()
            .collect()
    }

    pub fn snapshot(&self, resource_type: ResourceType) -> BTreeMap<String, Any> {
        self.resources
            .iter()
            .filter(|((stored_type, _), _)| *stored_type == resource_type)
            .map(|((_, name), resource)| (name.clone(), resource.payload().clone()))
            .collect()
    }

    pub fn resources_with_prefix(
        &self,
        resource_type: ResourceType,
        prefix: &str,
    ) -> Vec<XdsResource> {
        self.resources
            .iter()
            .filter(|((stored_type, name), _)| {
                *stored_type == resource_type && name.starts_with(prefix)
            })
            .map(|(_, resource)| resource.clone())
            .collect()
    }

    pub fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
        self.resources
            .values()
            .filter_map(XdsResource::sandbox_id)
            .collect()
    }

    pub fn version(&self) -> u64 {
        self.version
    }

    pub fn apply_batch(
        &mut self,
        groups: Vec<(ResourceType, Vec<InventoryMutation>)>,
    ) -> InventoryApplyResult {
        let groups = groups
            .into_iter()
            .filter(|(_, mutations)| !mutations.is_empty())
            .collect::<Vec<_>>();
        if groups.is_empty() {
            return InventoryApplyResult {
                version: self.version,
                changed_types: BTreeMap::new(),
            };
        }

        self.version = self.version.saturating_add(1);
        let version = self.version;
        let mut changed_types = BTreeMap::<SandboxId, BTreeSet<ResourceType>>::new();
        for (resource_type, mutations) in groups {
            let mut normalized = Vec::with_capacity(mutations.len());
            for mutation in mutations {
                let mutation = match mutation {
                    InventoryMutation::Upsert(resource) => {
                        if let Some(sandbox_id) = resource.sandbox_id() {
                            changed_types
                                .entry(sandbox_id)
                                .or_default()
                                .insert(resource_type);
                        }
                        self.upsert(resource.clone());
                        InventoryMutation::Upsert(resource)
                    }
                    InventoryMutation::Remove {
                        sandbox_id,
                        resource_type,
                        name,
                    } => {
                        let removed = self.remove(resource_type, &name);
                        let sandbox_id = sandbox_id
                            .or_else(|| removed.as_ref().and_then(XdsResource::sandbox_id));
                        if let Some(sandbox_id) = sandbox_id {
                            changed_types
                                .entry(sandbox_id)
                                .or_default()
                                .insert(resource_type);
                        }
                        InventoryMutation::Remove {
                            sandbox_id,
                            resource_type,
                            name,
                        }
                    }
                };
                normalized.push(mutation);
            }
            self.change_log.push(VersionedResourceChange::new(
                version,
                resource_type,
                normalized,
            ));
        }
        if self.change_log.len() > self.change_log_limit {
            let remove_count = self.change_log.len() - self.change_log_limit;
            self.change_log.drain(..remove_count);
        }
        InventoryApplyResult {
            version,
            changed_types,
        }
    }

    pub fn changes_since(&self, version: u64) -> Option<Vec<VersionedResourceChange>> {
        let Some(first) = self.change_log.first() else {
            return Some(Vec::new());
        };
        if version < first.version.saturating_sub(1) {
            return None;
        }
        Some(
            self.change_log
                .iter()
                .filter(|change| change.version > version)
                .cloned()
                .collect(),
        )
    }

    pub(crate) fn all(&self) -> impl Iterator<Item = &XdsResource> {
        self.resources.values()
    }
}
