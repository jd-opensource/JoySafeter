use std::collections::{HashMap, HashSet, VecDeque};

use envoy_types::pb::envoy::service::discovery::v3::{DeltaDiscoveryResponse, Resource};
use sha2::{Digest, Sha256};

use crate::ids::SandboxId;
use crate::xds::delivery::DeliveredResource;
use crate::xds::model::{ManagedXdsResource, ResourceOwner, ResourceType};

pub(super) const NONCE_TRACK_LIMIT: usize = 512;

pub(super) struct RemovedResource {
    name: String,
    owner: Option<ResourceOwner>,
}

impl RemovedResource {
    pub(super) fn attributed(name: String, owner: ResourceOwner) -> Self {
        Self {
            name,
            owner: Some(owner),
        }
    }

    fn client_only(name: String) -> Self {
        Self { name, owner: None }
    }
}

#[derive(Default)]
pub(super) struct NonceTracker {
    pub(super) entries: HashMap<String, (ResourceType, u64, Vec<DeliveredResource>)>,
    order: VecDeque<String>,
}

impl NonceTracker {
    pub(super) fn insert(
        &mut self,
        nonce: String,
        entry: (ResourceType, u64, Vec<DeliveredResource>),
    ) {
        if self.entries.insert(nonce.clone(), entry).is_none() {
            self.order.push_back(nonce);
        }
        while self.order.len() > NONCE_TRACK_LIMIT {
            if let Some(oldest) = self.order.pop_front() {
                self.entries.remove(&oldest);
            }
        }
    }

    pub(super) fn take(
        &mut self,
        nonce: &str,
    ) -> Option<(ResourceType, u64, Vec<DeliveredResource>)> {
        let entry = self.entries.remove(nonce);
        if entry.is_some() {
            self.order.retain(|candidate| candidate != nonce);
        }
        entry
    }
}

pub(super) fn sanitize_xds_nack(message: &str) -> String {
    let digest = Sha256::digest(message.as_bytes());
    format!(
        "Envoy rejected xDS resource (details redacted, bytes={}, fingerprint={})",
        message.len(),
        hex::encode(&digest[..8])
    )
}

#[allow(clippy::too_many_arguments)] // Inputs are the explicit state of one Delta xDS snapshot.
pub(super) fn snapshot_response(
    resource_type: ResourceType,
    version: u64,
    ownership_revision: u64,
    snapshot: Vec<ManagedXdsResource>,
    initial_resource_versions: &HashMap<String, String>,
    forced_sandboxes: &HashSet<SandboxId>,
    remove_client_only: bool,
    nonces: &mut NonceTracker,
) -> (DeltaDiscoveryResponse, HashMap<String, ResourceOwner>) {
    let current = snapshot
        .iter()
        .map(|resource| (resource.name.clone(), resource.owner))
        .collect::<HashMap<_, _>>();
    let authoritative_version = version.to_string();
    let upserts = snapshot
        .into_iter()
        .filter(|resource| {
            matches!(resource.owner, ResourceOwner::Sandbox(sandbox_id) if forced_sandboxes.contains(&sandbox_id))
                || initial_resource_versions.get(&resource.name) != Some(&authoritative_version)
        })
        .collect();
    let mut removals = if remove_client_only {
        initial_resource_versions
            .keys()
            .filter(|name| !current.contains_key(*name))
            .cloned()
            .map(RemovedResource::client_only)
            .collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    removals.sort_unstable_by(|left, right| left.name.cmp(&right.name));
    let response = delta_response(
        resource_type,
        version,
        ownership_revision,
        upserts,
        removals,
        nonces,
    );
    (response, current)
}

pub(super) fn delta_response(
    resource_type: ResourceType,
    version: u64,
    ownership_revision: u64,
    upserts: Vec<ManagedXdsResource>,
    removals: Vec<RemovedResource>,
    nonces: &mut NonceTracker,
) -> DeltaDiscoveryResponse {
    let delivered_resources = upserts
        .iter()
        .map(|resource| DeliveredResource {
            name: resource.name.clone(),
            owner: resource.owner,
            removed: false,
        })
        .chain(removals.iter().filter_map(|removal| {
            removal.owner.map(|owner| DeliveredResource {
                name: removal.name.clone(),
                owner,
                removed: true,
            })
        }))
        .collect();
    let resources = upserts
        .into_iter()
        .map(|resource| Resource {
            name: resource.name,
            version: version.to_string(),
            resource: Some(resource.payload),
            ..Default::default()
        })
        .collect();
    let removed_resources = removals.into_iter().map(|removal| removal.name).collect();
    let type_url = resource_type.type_url().to_string();
    let nonce = format!("n-{type_url}-{version}-{ownership_revision}");
    nonces.insert(nonce.clone(), (resource_type, version, delivered_resources));
    DeltaDiscoveryResponse {
        system_version_info: version.to_string(),
        resources,
        removed_resources,
        type_url,
        nonce,
        ..Default::default()
    }
}
