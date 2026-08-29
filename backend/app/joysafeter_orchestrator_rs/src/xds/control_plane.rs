use std::collections::{BTreeMap, BTreeSet, HashSet};

use crate::ids::SandboxId;

use super::ack_tracker::{AckDisposition, AckRecordOutcome, AckReport, AckTracker, ApplyStatus};
use super::inventory::{
    InventoryApplyResult, InventoryMutation, ResourceInventory, VersionedResourceChange,
    XdsResource,
};
use super::model::{
    ApplyTicket, AuthorityEpoch, NodeId, PlacementRevision, PolicyGeneration, ResourceType,
    StreamId,
};
use super::node_registry::{NodeRegistry, PlacementChange};

#[derive(Clone, Debug, Default, PartialEq)]
pub struct AudienceDelta {
    revision: Option<PlacementRevision>,
    upserts: BTreeMap<NodeId, Vec<XdsResource>>,
    removals: BTreeMap<NodeId, Vec<String>>,
}

impl AudienceDelta {
    pub fn revision(&self) -> PlacementRevision {
        self.revision.unwrap_or_else(|| PlacementRevision::new(0))
    }

    pub fn upserts(&self) -> &BTreeMap<NodeId, Vec<XdsResource>> {
        &self.upserts
    }

    pub fn removals(&self) -> &BTreeMap<NodeId, Vec<String>> {
        &self.removals
    }

    pub fn upserts_for(&self, node_id: &NodeId) -> &[XdsResource] {
        self.upserts.get(node_id).map(Vec::as_slice).unwrap_or(&[])
    }

    pub fn removals_for(&self, node_id: &NodeId) -> &[String] {
        self.removals.get(node_id).map(Vec::as_slice).unwrap_or(&[])
    }
}

pub struct XdsControlPlane {
    inventory: ResourceInventory,
    nodes: NodeRegistry,
    acknowledgements: AckTracker,
    authority_epoch: AuthorityEpoch,
}

impl Default for XdsControlPlane {
    fn default() -> Self {
        Self {
            inventory: ResourceInventory::default(),
            nodes: NodeRegistry::default(),
            acknowledgements: AckTracker::default(),
            authority_epoch: AuthorityEpoch::new(1),
        }
    }
}

impl XdsControlPlane {
    pub fn standalone() -> Self {
        Self {
            inventory: ResourceInventory::default(),
            nodes: NodeRegistry::new(false),
            acknowledgements: AckTracker::default(),
            authority_epoch: AuthorityEpoch::new(1),
        }
    }

    pub fn enable_node_aware(&mut self) {
        self.nodes.enable_node_aware();
    }

    pub fn begin_authority_epoch(&mut self, epoch: AuthorityEpoch) {
        self.authority_epoch = epoch;
        self.acknowledgements.revoke();
    }

    pub fn revoke_authority(&mut self) {
        self.acknowledgements.revoke();
    }

    pub fn upsert_resource(&mut self, resource: XdsResource) -> Option<XdsResource> {
        self.inventory.upsert(resource)
    }

    pub fn assign_node(&mut self, sandbox_id: SandboxId, node_id: NodeId) -> AudienceDelta {
        let change = self.nodes.assign(sandbox_id, node_id);
        self.retarget_pending_after_placement_change();
        self.delta_for(change)
    }

    pub fn remove_node(&mut self, sandbox_id: SandboxId) -> Option<AudienceDelta> {
        let change = self.nodes.remove(sandbox_id)?;
        self.retarget_pending_after_placement_change();
        Some(self.delta_for(change))
    }

    pub fn resources_for_node(&self, node_id: &NodeId) -> Vec<XdsResource> {
        self.inventory
            .all()
            .filter(|resource| {
                self.nodes
                    .resource_is_visible_to(resource.sandbox_id(), node_id)
            })
            .cloned()
            .collect()
    }

    pub fn snapshot_type(&self, resource_type: ResourceType) -> BTreeMap<String, prost_types::Any> {
        self.inventory.snapshot(resource_type)
    }

    pub fn snapshot_for_node(
        &self,
        resource_type: ResourceType,
        node_id: &NodeId,
    ) -> BTreeMap<String, prost_types::Any> {
        self.inventory
            .all()
            .filter(|resource| resource.resource_type() == resource_type)
            .filter(|resource| {
                self.nodes
                    .resource_is_visible_to(resource.sandbox_id(), node_id)
            })
            .map(|resource| (resource.name().to_string(), resource.payload().clone()))
            .collect()
    }

    pub fn changes_since(&self, version: u64) -> Option<Vec<VersionedResourceChange>> {
        self.inventory.changes_since(version)
    }

    pub fn changes_since_for_node(
        &self,
        version: u64,
        node_id: &NodeId,
    ) -> Option<Vec<VersionedResourceChange>> {
        self.inventory.changes_since(version).map(|changes| {
            changes
                .into_iter()
                .filter_map(|change| {
                    let mutations = change
                        .mutations()
                        .iter()
                        .filter(|mutation| {
                            self.nodes
                                .resource_is_visible_to(mutation.sandbox_id(), node_id)
                        })
                        .cloned()
                        .collect::<Vec<_>>();
                    if mutations.is_empty() {
                        None
                    } else {
                        Some(VersionedResourceChange::new(
                            change.version(),
                            change.resource_type(),
                            mutations,
                        ))
                    }
                })
                .collect()
        })
    }

    pub fn apply_batch(
        &mut self,
        groups: Vec<(ResourceType, Vec<InventoryMutation>)>,
        pending_sandboxes: impl IntoIterator<Item = SandboxId>,
    ) -> InventoryApplyResult {
        let result = self.inventory.apply_batch(groups);
        for sandbox_id in pending_sandboxes {
            let required_types = result.changed_types_for(sandbox_id);
            if required_types.is_empty() {
                continue;
            }
            self.acknowledgements.begin(ApplyTicket::new(
                sandbox_id,
                self.authority_epoch,
                PolicyGeneration::new(result.version()),
                self.nodes.revision(),
                self.expected_nodes(sandbox_id),
                required_types,
            ));
        }
        result
    }

    pub fn version(&self) -> u64 {
        self.inventory.version()
    }

    pub fn placement_revision(&self) -> PlacementRevision {
        self.nodes.revision()
    }

    pub fn resources_with_prefix(
        &self,
        resource_type: ResourceType,
        prefix: &str,
    ) -> Vec<XdsResource> {
        self.inventory.resources_with_prefix(resource_type, prefix)
    }

    pub fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
        self.inventory.configured_sandbox_ids()
    }

    pub fn register_stream(&mut self, node_id: NodeId, stream_id: StreamId) {
        self.acknowledgements
            .register_stream(node_id.clone(), stream_id);
        if !self.nodes.is_node_aware() {
            let pending = self.acknowledgements.pending_sandbox_ids();
            let revision = self.nodes.revision();
            for sandbox_id in pending {
                self.acknowledgements
                    .retarget(sandbox_id, revision, [node_id.clone()]);
            }
        }
    }

    pub fn unregister_stream(&mut self, node_id: &NodeId, stream_id: StreamId) {
        self.acknowledgements.unregister_stream(node_id, stream_id);
    }

    pub fn record_response(
        &mut self,
        resource_names: &[String],
        version: u64,
        placement_revision: PlacementRevision,
        node_id: &NodeId,
        stream_id: StreamId,
        resource_type: ResourceType,
        disposition: AckDisposition,
    ) -> Vec<AckRecordOutcome> {
        resource_names
            .iter()
            .filter_map(|name| sandbox_id_from_resource_name(name))
            .collect::<BTreeSet<_>>()
            .into_iter()
            .filter_map(|sandbox_id| {
                self.acknowledgements.ticket(sandbox_id)?;
                Some(self.acknowledgements.record(AckReport {
                    sandbox_id,
                    authority_epoch: self.authority_epoch,
                    generation: PolicyGeneration::new(version),
                    placement_revision,
                    node_id: node_id.clone(),
                    stream_id,
                    resource_type,
                    disposition: disposition.clone(),
                }))
            })
            .collect()
    }

    pub fn apply_status(&self, sandbox_id: SandboxId) -> Option<ApplyStatus> {
        self.acknowledgements.status(sandbox_id)
    }

    pub fn forget_sandbox(&mut self, sandbox_id: SandboxId) {
        self.acknowledgements.forget(sandbox_id);
    }

    fn delta_for(&self, change: PlacementChange) -> AudienceDelta {
        let mut delta = AudienceDelta {
            revision: Some(change.revision),
            ..AudienceDelta::default()
        };
        if !change.changed {
            return delta;
        }
        let resources = self.inventory.for_sandbox(change.sandbox_id);
        if let Some(previous_node) = change.previous_node {
            delta.removals.insert(
                previous_node,
                resources
                    .iter()
                    .map(|resource| resource.name().to_string())
                    .collect(),
            );
        }
        if let Some(current_node) = change.current_node {
            delta.upserts.insert(current_node, resources);
        }
        delta
    }

    fn expected_nodes(&self, sandbox_id: SandboxId) -> Vec<NodeId> {
        if let Some(owner) = self.nodes.owner(sandbox_id) {
            return vec![owner.clone()];
        }
        if self.nodes.is_node_aware() {
            return Vec::new();
        }
        self.acknowledgements
            .latest_stream_node()
            .into_iter()
            .collect()
    }

    fn retarget_pending_after_placement_change(&mut self) {
        let revision = self.nodes.revision();
        let targets = self
            .acknowledgements
            .pending_sandbox_ids()
            .into_iter()
            .map(|sandbox_id| (sandbox_id, self.expected_nodes(sandbox_id)))
            .collect::<Vec<_>>();
        for (sandbox_id, expected_nodes) in targets {
            self.acknowledgements
                .retarget(sandbox_id, revision, expected_nodes);
        }
    }
}

pub fn sandbox_id_from_resource_name(name: &str) -> Option<SandboxId> {
    let candidate = if let Some(listener_id) = name.strip_suffix("_http") {
        listener_id
    } else if let Some(cluster_name) = name.strip_prefix("up_") {
        cluster_name.split_once('_')?.0
    } else {
        return None;
    };
    uuid::Uuid::parse_str(candidate)
        .ok()
        .map(SandboxId::from_uuid)
}
