use std::collections::{HashMap, HashSet};

use envoy_types::pb::envoy::service::discovery::v3::DeltaDiscoveryResponse;
use tonic::Status;

use super::response::{delta_response, NonceTracker, RemovedResource};
use super::RESOURCE_TYPES;
use crate::xds::delivery::NodeSessionId;
use crate::xds::model::{ManagedXdsResource, ResourceOwner, ResourceType};
use crate::xds::node_health::EnvoyNodeHealthRegistry;
use crate::xds::node_ownership::NodeOwnershipRegistry;
use crate::xds::resource_store::{ManagedResourceChange, WorldRevision, XdsResourceStore};

pub(super) async fn visible_snapshot(
    resources: &XdsResourceStore,
    ownership: &NodeOwnershipRegistry,
    resource_type: ResourceType,
    node: &str,
) -> Vec<ManagedXdsResource> {
    resources
        .snapshot_type(resource_type)
        .await
        .into_iter()
        .filter(|resource| ownership.is_visible(resource.owner, node))
        .collect()
}

#[allow(clippy::too_many_arguments)] // Explicit stream state keeps revision delivery ownership visible.
pub(super) async fn send_revisions(
    sender: &tokio::sync::mpsc::Sender<Result<DeltaDiscoveryResponse, Status>>,
    ownership: &NodeOwnershipRegistry,
    node: &str,
    subscribed: &HashSet<ResourceType>,
    sent: &mut HashMap<ResourceType, HashMap<String, ResourceOwner>>,
    nonces: &mut NonceTracker,
    node_health: &EnvoyNodeHealthRegistry,
    session: NodeSessionId,
    revisions: Vec<WorldRevision>,
) -> Result<(), ()> {
    for revision in revisions {
        for resource_type in RESOURCE_TYPES {
            if !subscribed.contains(&resource_type) {
                continue;
            }
            let sent_for_type = sent.entry(resource_type).or_default();
            let mut upserts = Vec::new();
            let mut removals = Vec::new();
            for change in revision
                .changes
                .iter()
                .filter(|change| change.resource_type() == resource_type)
            {
                match change {
                    ManagedResourceChange::Upsert(resource) => {
                        if ownership.is_visible(resource.owner, node) {
                            sent_for_type.insert(resource.name.clone(), resource.owner);
                            upserts.push(resource.clone());
                        } else if let Some(previous_owner) = sent_for_type.remove(&resource.name) {
                            removals.push(RemovedResource::attributed(
                                resource.name.clone(),
                                previous_owner,
                            ));
                        }
                    }
                    ManagedResourceChange::Remove { name, owner, .. } => {
                        if let Some(previous_owner) = sent_for_type.remove(name) {
                            debug_assert_eq!(previous_owner, *owner);
                            removals
                                .push(RemovedResource::attributed(name.clone(), previous_owner));
                        }
                    }
                }
            }
            if upserts.is_empty() && removals.is_empty() {
                continue;
            }
            let response = delta_response(
                resource_type,
                revision.version,
                ownership.current_revision(),
                upserts,
                removals,
                nonces,
            );
            if send_response(sender, node_health, node, session, response)
                .await
                .is_err()
            {
                return Err(());
            }
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)] // Explicit stream state keeps reconciliation ownership visible.
pub(super) async fn send_full_reconciliation(
    sender: &tokio::sync::mpsc::Sender<Result<DeltaDiscoveryResponse, Status>>,
    resources: &XdsResourceStore,
    ownership: &NodeOwnershipRegistry,
    node: &str,
    subscribed: &HashSet<ResourceType>,
    sent: &mut HashMap<ResourceType, HashMap<String, ResourceOwner>>,
    nonces: &mut NonceTracker,
    node_health: &EnvoyNodeHealthRegistry,
    session: NodeSessionId,
    version: u64,
) -> Result<(), ()> {
    for resource_type in RESOURCE_TYPES {
        if !subscribed.contains(&resource_type) {
            continue;
        }
        let snapshot = visible_snapshot(resources, ownership, resource_type, node).await;
        let previous = sent.entry(resource_type).or_default();
        let current = snapshot
            .iter()
            .map(|resource| (resource.name.clone(), resource.owner))
            .collect::<HashMap<_, _>>();
        let removals = previous
            .iter()
            .filter(|(name, _)| !current.contains_key(*name))
            .map(|(name, owner)| RemovedResource::attributed(name.clone(), *owner))
            .collect::<Vec<_>>();
        let response = delta_response(
            resource_type,
            version,
            ownership.current_revision(),
            snapshot,
            removals,
            nonces,
        );
        *previous = current;
        if send_response(sender, node_health, node, session, response)
            .await
            .is_err()
        {
            return Err(());
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)] // Explicit stream state keeps reconciliation ownership visible.
pub(super) async fn send_visibility_reconciliation(
    sender: &tokio::sync::mpsc::Sender<Result<DeltaDiscoveryResponse, Status>>,
    resources: &XdsResourceStore,
    ownership: &NodeOwnershipRegistry,
    node: &str,
    subscribed: &HashSet<ResourceType>,
    sent: &mut HashMap<ResourceType, HashMap<String, ResourceOwner>>,
    nonces: &mut NonceTracker,
    node_health: &EnvoyNodeHealthRegistry,
    session: NodeSessionId,
    version: u64,
) -> Result<(), ()> {
    for resource_type in RESOURCE_TYPES {
        if !subscribed.contains(&resource_type) {
            continue;
        }
        let snapshot = visible_snapshot(resources, ownership, resource_type, node).await;
        let current_by_name = snapshot
            .into_iter()
            .map(|resource| (resource.name.clone(), resource))
            .collect::<HashMap<_, _>>();
        let previous = sent.entry(resource_type).or_default();
        let current = current_by_name
            .iter()
            .map(|(name, resource)| (name.clone(), resource.owner))
            .collect::<HashMap<_, _>>();
        let upserts = current
            .keys()
            .filter(|name| !previous.contains_key(*name))
            .filter_map(|name| current_by_name.get(name).cloned())
            .collect::<Vec<_>>();
        let removals = previous
            .iter()
            .filter(|(name, _)| !current.contains_key(*name))
            .map(|(name, owner)| RemovedResource::attributed(name.clone(), *owner))
            .collect::<Vec<_>>();
        *previous = current;
        if upserts.is_empty() && removals.is_empty() {
            continue;
        }
        let response = delta_response(
            resource_type,
            version,
            ownership.current_revision(),
            upserts,
            removals,
            nonces,
        );
        if send_response(sender, node_health, node, session, response)
            .await
            .is_err()
        {
            return Err(());
        }
    }
    Ok(())
}

pub(super) async fn send_response(
    sender: &tokio::sync::mpsc::Sender<Result<DeltaDiscoveryResponse, Status>>,
    node_health: &EnvoyNodeHealthRegistry,
    node: &str,
    session: NodeSessionId,
    response: DeltaDiscoveryResponse,
) -> Result<(), ()> {
    let resource_type = ResourceType::from_type_url(&response.type_url).ok_or(())?;
    node_health.mark_pending(node, session, resource_type, &response.nonce);
    sender.send(Ok(response)).await.map_err(|_| ())
}
