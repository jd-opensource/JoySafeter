//! Atomic, explicitly-owned xDS resource world and semantic revision log.

use std::collections::{HashMap, HashSet, VecDeque};
use std::sync::Arc;

use tokio::sync::{watch, RwLock};

use crate::ids::SandboxId;

use super::model::{ManagedXdsResource, ResourceOwner, ResourceType, SandboxResourceBundle};

const REVISION_LOG_LIMIT: usize = 512;

#[derive(Debug, Clone, PartialEq)]
pub enum ManagedResourceChange {
    Upsert(ManagedXdsResource),
    Remove {
        name: String,
        resource_type: ResourceType,
        owner: ResourceOwner,
    },
}

impl ManagedResourceChange {
    pub fn resource_type(&self) -> ResourceType {
        match self {
            Self::Upsert(resource) => resource.resource_type,
            Self::Remove { resource_type, .. } => *resource_type,
        }
    }

    pub fn owner(&self) -> ResourceOwner {
        match self {
            Self::Upsert(resource) => resource.owner,
            Self::Remove { owner, .. } => *owner,
        }
    }

    pub fn name(&self) -> &str {
        match self {
            Self::Upsert(resource) => &resource.name,
            Self::Remove { name, .. } => name,
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct WorldRevision {
    pub version: u64,
    pub changes: Vec<ManagedResourceChange>,
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct ResourceKey {
    resource_type: ResourceType,
    name: String,
}

impl ResourceKey {
    fn of(resource: &ManagedXdsResource) -> Self {
        Self {
            resource_type: resource.resource_type,
            name: resource.name.clone(),
        }
    }
}

#[derive(Default)]
struct ResourceWorld {
    version: u64,
    resources: HashMap<ResourceKey, ManagedXdsResource>,
    revisions: VecDeque<WorldRevision>,
}

#[derive(Clone)]
pub struct XdsResourceStore {
    world: Arc<RwLock<ResourceWorld>>,
    revision: watch::Sender<u64>,
}

impl XdsResourceStore {
    pub fn new() -> Self {
        let (revision, _receiver) = watch::channel(0);
        Self {
            world: Arc::new(RwLock::new(ResourceWorld::default())),
            revision,
        }
    }

    pub async fn replace_inventory(
        &self,
        resources: Vec<ManagedXdsResource>,
    ) -> anyhow::Result<WorldRevision> {
        let replacement = validated_resource_map(resources)?;
        let mut world = self.world.write().await;
        let mut changes = Vec::new();

        for (key, existing) in &world.resources {
            if !replacement.contains_key(key) {
                changes.push(remove_change(existing));
            }
        }
        for (key, resource) in &replacement {
            if world.resources.get(key) != Some(resource) {
                changes.push(ManagedResourceChange::Upsert(resource.clone()));
            }
        }

        sort_changes(&mut changes);
        if changes.is_empty() {
            return Ok(WorldRevision {
                version: world.version,
                changes,
            });
        }
        world.resources = replacement;
        Ok(self.commit_revision(&mut world, changes))
    }

    pub async fn apply_bundle(
        &self,
        bundle: SandboxResourceBundle,
    ) -> anyhow::Result<WorldRevision> {
        let expected_owner = ResourceOwner::Sandbox(bundle.sandbox_id);
        for resource in &bundle.resources {
            if resource.owner != expected_owner {
                anyhow::bail!(
                    "xDS resource {} owner does not match bundle sandbox {}",
                    resource.name,
                    bundle.sandbox_id
                );
            }
        }
        self.replace_owner_resources(expected_owner, bundle.resources)
            .await
    }

    pub(crate) async fn replace_owner_resources(
        &self,
        owner: ResourceOwner,
        resources: Vec<ManagedXdsResource>,
    ) -> anyhow::Result<WorldRevision> {
        for resource in &resources {
            if resource.owner != owner {
                anyhow::bail!("xDS resource {} has an unexpected owner", resource.name);
            }
        }
        let replacement = validated_resource_map(resources)?;
        let mut world = self.world.write().await;

        for (key, resource) in &replacement {
            if let Some(existing) = world.resources.get(key) {
                if existing.owner != owner {
                    anyhow::bail!(
                        "xDS resource {} is already owned by another resource owner",
                        resource.name
                    );
                }
            }
        }

        let replacement_keys = replacement.keys().cloned().collect::<HashSet<_>>();
        let mut changes = world
            .resources
            .iter()
            .filter(|(key, resource)| resource.owner == owner && !replacement_keys.contains(*key))
            .map(|(_, resource)| remove_change(resource))
            .collect::<Vec<_>>();

        for (key, resource) in &replacement {
            if world.resources.get(key) != Some(resource) {
                changes.push(ManagedResourceChange::Upsert(resource.clone()));
            }
        }
        sort_changes(&mut changes);
        if changes.is_empty() {
            return Ok(WorldRevision {
                version: world.version,
                changes,
            });
        }

        world
            .resources
            .retain(|_, resource| resource.owner != owner);
        world.resources.extend(replacement);
        Ok(self.commit_revision(&mut world, changes))
    }

    pub(crate) async fn reannounce_owner(&self, owner: ResourceOwner) -> WorldRevision {
        let mut world = self.world.write().await;
        let mut changes = world
            .resources
            .values()
            .filter(|resource| resource.owner == owner)
            .cloned()
            .map(ManagedResourceChange::Upsert)
            .collect::<Vec<_>>();
        sort_changes(&mut changes);
        if changes.is_empty() {
            return WorldRevision {
                version: world.version,
                changes,
            };
        }
        self.commit_revision(&mut world, changes)
    }

    pub async fn remove_sandbox(&self, sandbox_id: SandboxId) -> WorldRevision {
        let owner = ResourceOwner::Sandbox(sandbox_id);
        let mut world = self.world.write().await;
        let mut changes = world
            .resources
            .values()
            .filter(|resource| resource.owner == owner)
            .map(remove_change)
            .collect::<Vec<_>>();
        sort_changes(&mut changes);
        if changes.is_empty() {
            return WorldRevision {
                version: world.version,
                changes,
            };
        }
        world
            .resources
            .retain(|_, resource| resource.owner != owner);
        self.commit_revision(&mut world, changes)
    }

    pub async fn resources_owned_by(&self, owner: ResourceOwner) -> Vec<ManagedXdsResource> {
        let world = self.world.read().await;
        let mut resources = world
            .resources
            .values()
            .filter(|resource| resource.owner == owner)
            .cloned()
            .collect::<Vec<_>>();
        sort_resources(&mut resources);
        resources
    }

    pub async fn snapshot_type(&self, resource_type: ResourceType) -> Vec<ManagedXdsResource> {
        let world = self.world.read().await;
        let mut resources = world
            .resources
            .values()
            .filter(|resource| resource.resource_type == resource_type)
            .cloned()
            .collect::<Vec<_>>();
        sort_resources(&mut resources);
        resources
    }

    pub async fn current_version(&self) -> u64 {
        self.world.read().await.version
    }

    pub async fn changes_since(&self, version: u64) -> Option<Vec<WorldRevision>> {
        let world = self.world.read().await;
        let Some(first) = world.revisions.front() else {
            return Some(Vec::new());
        };
        if version < first.version.saturating_sub(1) {
            return None;
        }
        Some(
            world
                .revisions
                .iter()
                .filter(|revision| revision.version > version)
                .cloned()
                .collect(),
        )
    }

    pub fn subscribe(&self) -> watch::Receiver<u64> {
        self.revision.subscribe()
    }

    fn commit_revision(
        &self,
        world: &mut ResourceWorld,
        changes: Vec<ManagedResourceChange>,
    ) -> WorldRevision {
        world.version = world.version.saturating_add(1);
        let revision = WorldRevision {
            version: world.version,
            changes,
        };
        world.revisions.push_back(revision.clone());
        while world.revisions.len() > REVISION_LOG_LIMIT {
            world.revisions.pop_front();
        }
        self.revision.send_replace(world.version);
        revision
    }
}

impl Default for XdsResourceStore {
    fn default() -> Self {
        Self::new()
    }
}

fn validated_resource_map(
    resources: Vec<ManagedXdsResource>,
) -> anyhow::Result<HashMap<ResourceKey, ManagedXdsResource>> {
    let mut validated = HashMap::with_capacity(resources.len());
    for resource in resources {
        if resource.payload.type_url != resource.resource_type.type_url() {
            anyhow::bail!(
                "xDS resource {} payload type URL {} does not match declared type {}",
                resource.name,
                resource.payload.type_url,
                resource.resource_type.type_url()
            );
        }
        let key = ResourceKey::of(&resource);
        if validated.insert(key, resource).is_some() {
            anyhow::bail!("duplicate xDS resource name within one resource type");
        }
    }
    Ok(validated)
}

fn remove_change(resource: &ManagedXdsResource) -> ManagedResourceChange {
    ManagedResourceChange::Remove {
        name: resource.name.clone(),
        resource_type: resource.resource_type,
        owner: resource.owner,
    }
}

fn sort_resources(resources: &mut [ManagedXdsResource]) {
    resources.sort_by(|left, right| {
        left.resource_type
            .delivery_order()
            .cmp(&right.resource_type.delivery_order())
            .then_with(|| left.name.cmp(&right.name))
    });
}

fn sort_changes(changes: &mut [ManagedResourceChange]) {
    changes.sort_by(|left, right| {
        left.resource_type()
            .delivery_order()
            .cmp(&right.resource_type().delivery_order())
            .then_with(|| left.name().cmp(right.name()))
            .then_with(|| change_order(left).cmp(&change_order(right)))
    });
}

fn change_order(change: &ManagedResourceChange) -> u8 {
    match change {
        ManagedResourceChange::Upsert(_) => 0,
        ManagedResourceChange::Remove { .. } => 1,
    }
}
