//! Delta ADS transport over the authoritative resource and node registries.

use futures::Stream;
use std::collections::{HashMap, HashSet, VecDeque};
use std::pin::Pin;
use std::sync::Arc;
use tokio::sync::{watch, Mutex};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status, Streaming};
use tracing::{debug, warn};

use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_server::AggregatedDiscoveryService, DeltaDiscoveryRequest,
    DeltaDiscoveryResponse, DiscoveryRequest, DiscoveryResponse, Resource,
};

use crate::ids::SandboxId;

use super::authority::{RecoveryAuthorityGuard, XdsAuthority};
use super::delivery::{
    DeliveredResource, DeliveryAttempt, DeliveryCoordinator, DeliveryRequest, DeliveryTarget,
    NodeSessionId, ReceiptOutcome,
};
use super::inventory::{
    InstalledRecoveryInventory, RecoveryDelivery, RecoveryDeliveryState, RecoveryInventory,
};
use super::metrics::{XdsMetrics, XdsMetricsSnapshot, XdsStreamRejection};
use super::model::{ManagedXdsResource, ResourceOwner, ResourceType};
use super::node_ownership::{NodeOwnershipRegistry, OwnershipTransition};
use super::resource_store::{ManagedResourceChange, WorldRevision, XdsResourceStore};

const NONCE_TRACK_LIMIT: usize = 512;
const RESOURCE_TYPES: [ResourceType; 2] = [ResourceType::Cluster, ResourceType::Listener];

type DeltaStream = Pin<Box<dyn Stream<Item = Result<DeltaDiscoveryResponse, Status>> + Send>>;
type SotwStream = Pin<Box<dyn Stream<Item = Result<DiscoveryResponse, Status>> + Send>>;

struct RemovedResource {
    name: String,
    owner: Option<ResourceOwner>,
}

impl RemovedResource {
    fn attributed(name: String, owner: ResourceOwner) -> Self {
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
struct NonceTracker {
    entries: HashMap<String, (ResourceType, u64, Vec<DeliveredResource>)>,
    order: VecDeque<String>,
}

impl NonceTracker {
    fn insert(&mut self, nonce: String, entry: (ResourceType, u64, Vec<DeliveredResource>)) {
        if self.entries.insert(nonce.clone(), entry).is_none() {
            self.order.push_back(nonce);
        }
        while self.order.len() > NONCE_TRACK_LIMIT {
            if let Some(oldest) = self.order.pop_front() {
                self.entries.remove(&oldest);
            }
        }
    }

    fn take(&mut self, nonce: &str) -> Option<(ResourceType, u64, Vec<DeliveredResource>)> {
        let entry = self.entries.remove(nonce);
        if entry.is_some() {
            self.order.retain(|candidate| candidate != nonce);
        }
        entry
    }
}

pub struct DeltaXdsServer {
    resources: XdsResourceStore,
    node_ownership: NodeOwnershipRegistry,
    authority: XdsAuthority,
    mutation_lock: Arc<Mutex<()>>,
    delivery: Arc<Mutex<DeliveryCoordinator>>,
    delivery_notify: watch::Sender<u64>,
    metrics: XdsMetrics,
}

impl DeltaXdsServer {
    pub fn new(
        authority: XdsAuthority,
        resources: XdsResourceStore,
        node_ownership: NodeOwnershipRegistry,
    ) -> Arc<Self> {
        let (delivery_notify, _delivery_receiver) = watch::channel(0);
        Arc::new(Self {
            resources,
            node_ownership,
            authority,
            mutation_lock: Arc::new(Mutex::new(())),
            delivery: Arc::new(Mutex::new(DeliveryCoordinator::default())),
            delivery_notify,
            metrics: XdsMetrics::default(),
        })
    }

    pub async fn publish_sandbox_resources(
        &self,
        request: DeliveryRequest,
        target: DeliveryTarget,
        resources: Vec<ManagedXdsResource>,
    ) -> anyhow::Result<Option<DeliveryAttempt>> {
        request.validate()?;
        self.authority
            .validate_delivery_epoch(request.authority_epoch)?;
        let _guard = self.mutation_lock.lock().await;
        let mut revision = self
            .resources
            .replace_owner_resources(ResourceOwner::Sandbox(request.sandbox_id), resources)
            .await?;
        if revision.changes.is_empty() {
            revision = self
                .resources
                .reannounce_owner(ResourceOwner::Sandbox(request.sandbox_id))
                .await;
        }
        let required_types = revision
            .changes
            .iter()
            .map(ManagedResourceChange::resource_type)
            .collect::<HashSet<_>>();
        if required_types.is_empty() {
            return Ok(None);
        }
        let mut delivery = self.delivery.lock().await;
        let attempt = delivery.begin_attempt(request, target, required_types.clone())?;
        delivery.mark_published(attempt, revision.version, required_types)?;
        drop(delivery);
        self.notify_delivery_changed();
        Ok(Some(attempt))
    }

    pub async fn install_recovery_inventory(
        &self,
        authority: &RecoveryAuthorityGuard,
        inventory: RecoveryInventory,
    ) -> anyhow::Result<InstalledRecoveryInventory> {
        authority.validate()?;

        let mut prepared = Vec::with_capacity(inventory.recovered_sandboxes.len());
        let mut resources = Vec::new();
        for sandbox in &inventory.recovered_sandboxes {
            let request = DeliveryRequest {
                authority_epoch: authority.epoch(),
                sandbox_id: sandbox.sandbox_id,
                generation: sandbox.generation.clone(),
            };
            request.validate()?;
            let target = match self.node_ownership.delivery_owner_node(sandbox.sandbox_id) {
                Ok(Some(node)) => DeliveryTarget::Node(node),
                Ok(None) => DeliveryTarget::AnyNode,
                Err(_) => DeliveryTarget::Unavailable,
            };
            let required_types = sandbox
                .resources
                .iter()
                .map(|resource| resource.resource_type)
                .collect::<HashSet<_>>();
            if required_types.is_empty() {
                anyhow::bail!(
                    "recovered sandbox {} has no delivery quorum",
                    sandbox.sandbox_id
                );
            }
            if !matches!(target, DeliveryTarget::Unavailable) {
                resources.extend(sandbox.resources.iter().cloned());
            }
            prepared.push((request, target, required_types));
        }

        let _guard = self.mutation_lock.lock().await;
        authority.validate()?;
        let revision = self.resources.replace_inventory(resources).await?;
        let mut delivery = self.delivery.lock().await;
        delivery.clear_pending();
        let mut deliveries = Vec::with_capacity(prepared.len());
        for (request, target, required_types) in prepared {
            if matches!(target, DeliveryTarget::Unavailable) {
                deliveries.push(RecoveryDelivery {
                    sandbox_id: request.sandbox_id,
                    generation: request.generation,
                    state: RecoveryDeliveryState::Deferred,
                });
                continue;
            }
            let attempt =
                delivery.begin_attempt(request.clone(), target.clone(), required_types.clone())?;
            delivery.mark_published(attempt, revision.version, required_types)?;
            deliveries.push(RecoveryDelivery {
                sandbox_id: request.sandbox_id,
                generation: request.generation,
                state: RecoveryDeliveryState::Await(attempt),
            });
        }
        drop(delivery);
        self.notify_delivery_changed();
        let deferred_count = deliveries
            .iter()
            .filter(|delivery| matches!(delivery.state, RecoveryDeliveryState::Deferred))
            .count();
        self.metrics
            .set_degraded_inventory(deferred_count + inventory.quarantined_sandboxes.len());

        Ok(InstalledRecoveryInventory {
            deliveries,
            quarantined_sandboxes: inventory.quarantined_sandboxes,
        })
    }

    pub async fn remove_sandbox_resources(
        &self,
        sandbox_id: SandboxId,
        target: DeliveryTarget,
    ) -> anyhow::Result<Option<DeliveryAttempt>> {
        let _guard = self.mutation_lock.lock().await;
        let required_types = self
            .resources
            .resources_owned_by(ResourceOwner::Sandbox(sandbox_id))
            .await
            .into_iter()
            .map(|resource| resource.resource_type)
            .collect::<HashSet<_>>();
        if required_types.is_empty() {
            return Ok(None);
        }
        let mut delivery = self.delivery.lock().await;
        let request = delivery
            .current_request(sandbox_id)
            .ok_or(super::delivery::DeliveryError::MissingDeliveryContext)?;
        self.authority
            .validate_delivery_epoch(request.authority_epoch)?;
        if matches!(target, DeliveryTarget::Unavailable) {
            let revision = self.resources.remove_sandbox(sandbox_id).await;
            delivery.forget(sandbox_id);
            drop(delivery);
            if !revision.changes.is_empty() {
                self.notify_delivery_changed();
            }
            return Ok(None);
        }
        let attempt = delivery.begin_removal(sandbox_id, target, required_types.clone())?;
        let revision = self.resources.remove_sandbox(sandbox_id).await;
        delivery.mark_published(attempt, revision.version, required_types)?;
        drop(delivery);
        self.notify_delivery_changed();
        Ok(Some(attempt))
    }

    pub async fn assign_sandbox_node(
        &self,
        sandbox_id: SandboxId,
        node: impl Into<String>,
    ) -> anyhow::Result<Option<DeliveryAttempt>> {
        let _guard = self.mutation_lock.lock().await;
        let transition = self.node_ownership.assign(sandbox_id, node);
        self.record_ownership_transition(&transition);
        let target = match transition {
            OwnershipTransition::Assigned { node, .. }
            | OwnershipTransition::Moved { new_node: node, .. } => DeliveryTarget::Node(node),
            OwnershipTransition::Unchanged { .. } => return Ok(None),
            OwnershipTransition::Removed { .. } | OwnershipTransition::Missing { .. } => {
                unreachable!("assign cannot remove node ownership")
            }
        };
        let world_revision = self.resources.current_version().await;
        let attempt =
            self.delivery
                .lock()
                .await
                .retarget_current(sandbox_id, target, world_revision)?;
        if attempt.is_some() {
            self.notify_delivery_changed();
        }
        Ok(attempt)
    }

    pub async fn remove_sandbox_node(&self, sandbox_id: SandboxId) {
        let _guard = self.mutation_lock.lock().await;
        let transition = self.node_ownership.remove(sandbox_id);
        self.record_ownership_transition(&transition);
        if matches!(transition, OwnershipTransition::Removed { .. }) {
            self.delivery.lock().await.suspend_current(sandbox_id);
            self.notify_delivery_changed();
        }
    }

    pub async fn replace_node_assignments(
        &self,
        assignments: HashMap<SandboxId, String>,
    ) -> anyhow::Result<Vec<DeliveryAttempt>> {
        let _guard = self.mutation_lock.lock().await;
        let transitions = self.node_ownership.replace_all(assignments);
        let world_revision = self.resources.current_version().await;
        let mut delivery = self.delivery.lock().await;
        let mut attempts = Vec::new();
        let mut changed_delivery = false;
        for transition in transitions {
            self.record_ownership_transition(&transition);
            match transition {
                OwnershipTransition::Assigned {
                    sandbox_id, node, ..
                }
                | OwnershipTransition::Moved {
                    sandbox_id,
                    new_node: node,
                    ..
                } => {
                    if let Some(attempt) = delivery.retarget_current(
                        sandbox_id,
                        DeliveryTarget::Node(node),
                        world_revision,
                    )? {
                        attempts.push(attempt);
                        changed_delivery = true;
                    }
                }
                OwnershipTransition::Removed { sandbox_id, .. } => {
                    delivery.suspend_current(sandbox_id);
                    changed_delivery = true;
                }
                OwnershipTransition::Unchanged { .. } | OwnershipTransition::Missing { .. } => {}
            }
        }
        drop(delivery);
        if changed_delivery {
            self.notify_delivery_changed();
        }
        Ok(attempts)
    }

    pub async fn configured_sandbox_ids(&self, resource_type: ResourceType) -> HashSet<SandboxId> {
        self.resources
            .snapshot_type(resource_type)
            .await
            .into_iter()
            .filter_map(|resource| match resource.owner {
                ResourceOwner::Shared => None,
                ResourceOwner::Sandbox(sandbox_id) => Some(sandbox_id),
            })
            .collect()
    }

    pub(crate) fn delivery(&self) -> &Arc<Mutex<DeliveryCoordinator>> {
        &self.delivery
    }

    pub(crate) fn delivery_notify(&self) -> watch::Receiver<u64> {
        self.delivery_notify.subscribe()
    }

    pub(crate) fn notify_delivery_changed(&self) {
        let next_revision = (*self.delivery_notify.borrow()).saturating_add(1);
        self.delivery_notify.send_replace(next_revision);
    }

    pub(crate) fn metrics(&self) -> XdsMetrics {
        self.metrics.clone()
    }

    pub async fn metrics_snapshot(&self) -> XdsMetricsSnapshot {
        let delivery = self.delivery.lock().await.metrics_snapshot();
        self.metrics
            .snapshot(self.authority.metrics_snapshot(), delivery)
    }

    fn record_ownership_transition(&self, transition: &OwnershipTransition) {
        match transition {
            OwnershipTransition::Assigned { .. } => self.metrics.record_ownership_assigned(),
            OwnershipTransition::Moved { .. } => self.metrics.record_ownership_moved(),
            OwnershipTransition::Removed { .. } => self.metrics.record_ownership_removed(),
            OwnershipTransition::Unchanged { .. } | OwnershipTransition::Missing { .. } => {}
        }
    }
}

#[tonic::async_trait]
impl AggregatedDiscoveryService for DeltaXdsServer {
    type StreamAggregatedResourcesStream = SotwStream;

    async fn stream_aggregated_resources(
        &self,
        _request: Request<Streaming<DiscoveryRequest>>,
    ) -> Result<Response<Self::StreamAggregatedResourcesStream>, Status> {
        Err(Status::unimplemented(
            "only DeltaAggregatedResources is supported",
        ))
    }

    type DeltaAggregatedResourcesStream = DeltaStream;

    async fn delta_aggregated_resources(
        &self,
        request: Request<Streaming<DeltaDiscoveryRequest>>,
    ) -> Result<Response<Self::DeltaAggregatedResourcesStream>, Status> {
        let mut authority_receiver = self.authority.subscribe();
        if !authority_receiver.borrow_and_update().serves_ads() {
            self.metrics
                .record_rejected_stream(XdsStreamRejection::AuthorityUnavailable);
            return Err(Status::unavailable("xDS authority is not serving"));
        }

        let mut inbound = request.into_inner();
        let (sender, receiver) =
            tokio::sync::mpsc::channel::<Result<DeltaDiscoveryResponse, Status>>(16);
        let resources = self.resources.clone();
        let node_ownership = self.node_ownership.clone();
        let mutation_lock = self.mutation_lock.clone();
        let delivery = self.delivery.clone();
        let delivery_notify = self.delivery_notify.clone();
        let mut session_receiver = delivery_notify.subscribe();
        let metrics = self.metrics.clone();
        let mut resource_receiver = resources.subscribe();
        let mut ownership_receiver = node_ownership.subscribe();

        tokio::spawn(async move {
            let mut stream_node = String::new();
            let mut node_session = None::<NodeSessionId>;
            let mut nonces = NonceTracker::default();
            let mut subscribed = HashSet::<ResourceType>::new();
            let mut sent = HashMap::<ResourceType, HashMap<String, ResourceOwner>>::new();
            let mut last_seen_version = *resource_receiver.borrow_and_update();

            loop {
                tokio::select! {
                    biased;
                    changed = authority_receiver.changed() => {
                        if changed.is_err() || !authority_receiver.borrow_and_update().serves_ads() {
                            debug!("xDS authority revoked; closing ADS stream");
                            break;
                        }
                    }
                    changed = session_receiver.changed() => {
                        if changed.is_err() {
                            break;
                        }
                        session_receiver.borrow_and_update();
                        if let Some(session) = node_session {
                            if !delivery
                                .lock()
                                .await
                                .is_current_node_session(&stream_node, session)
                            {
                                metrics.record_stale_session_closure();
                                break;
                            }
                        }
                    }
                    request = inbound.message() => {
                        let request = match request {
                            Ok(Some(request)) => request,
                            Ok(None) => break,
                            Err(error) => {
                                debug!(%error, "xDS inbound stream failed");
                                break;
                            }
                        };
                        if stream_node.is_empty() {
                            let Some(node) = request.node.as_ref().filter(|node| !node.id.is_empty()) else {
                                metrics.record_rejected_stream(XdsStreamRejection::InvalidNodeIdentity);
                                let _ = sender
                                    .send(Err(Status::invalid_argument("first xDS request must include a node id")))
                                    .await;
                                break;
                            };
                            stream_node = node.id.clone();
                            let mut coordinator = delivery.lock().await;
                            node_session = Some(coordinator.open_node_session(stream_node.clone()));
                            drop(coordinator);
                            let next_revision = (*delivery_notify.borrow()).saturating_add(1);
                            delivery_notify.send_replace(next_revision);
                        } else if let Some(node) = request.node.as_ref().filter(|node| !node.id.is_empty()) {
                            if stream_node != node.id {
                                metrics.record_rejected_stream(XdsStreamRejection::InvalidNodeIdentity);
                                let _ = sender
                                    .send(Err(Status::invalid_argument("xDS node id changed within one stream")))
                                    .await;
                                break;
                            }
                        }
                        if !request.response_nonce.is_empty() {
                            if let Some((resource_type, world_revision, delivered_resources)) =
                                nonces.take(&request.response_nonce)
                            {
                                let session = node_session.expect("node session established with node id");
                                let mut coordinator = delivery.lock().await;
                                match coordinator.record_response(
                                    &stream_node,
                                    session,
                                    &request.response_nonce,
                                    world_revision,
                                    resource_type,
                                    &delivered_resources,
                                ) {
                                    Ok(ReceiptOutcome::Stale) => {}
                                    Ok(_) => {
                                        if let Some(error) = request.error_detail {
                                            warn!(code = error.code, message = %error.message, "Envoy NACK'd xDS update");
                                            let outcome = coordinator.reject(
                                                &stream_node,
                                                session,
                                                &request.response_nonce,
                                                error.message,
                                            );
                                            if matches!(outcome, ReceiptOutcome::Accepted | ReceiptOutcome::Completed) {
                                                metrics.record_nack(resource_type);
                                            }
                                        } else {
                                            let outcome = coordinator.acknowledge(
                                                &stream_node,
                                                session,
                                                &request.response_nonce,
                                            );
                                            if matches!(outcome, ReceiptOutcome::Accepted | ReceiptOutcome::Completed) {
                                                metrics.record_ack(resource_type);
                                            }
                                        }
                                        let next_revision = (*delivery_notify.borrow()).saturating_add(1);
                                        delivery_notify.send_replace(next_revision);
                                    }
                                    Err(error) => {
                                        warn!(%error, nonce = %request.response_nonce, "discarding invalid xDS delivery receipt");
                                    }
                                }
                            }
                        }
                        let Some(resource_type) = ResourceType::from_type_url(&request.type_url) else {
                            continue;
                        };
                        if subscribed.insert(resource_type) {
                            let _guard = mutation_lock.lock().await;
                            let version = resources.current_version().await;
                            let snapshot = visible_snapshot(
                                &resources,
                                &node_ownership,
                                resource_type,
                                &stream_node,
                            ).await;
                            let forced_sandboxes = delivery
                                .lock()
                                .await
                                .pending_sandboxes_for(&stream_node, resource_type);
                            let (response, current) = snapshot_response(
                                resource_type,
                                version,
                                node_ownership.current_revision(),
                                snapshot,
                                &request.initial_resource_versions,
                                &forced_sandboxes,
                                &mut nonces,
                            );
                            if !request.initial_resource_versions.is_empty() {
                                metrics.record_reconnect(
                                    response.resources.len(),
                                    response.removed_resources.len(),
                                );
                            }
                            sent.insert(resource_type, current);
                            if sender.send(Ok(response)).await.is_err() {
                                break;
                            }
                        }
                    }
                    changed = resource_receiver.changed() => {
                        if changed.is_err() {
                            break;
                        }
                        let version = *resource_receiver.borrow_and_update();
                        if version == last_seen_version {
                            continue;
                        }
                        let _guard = mutation_lock.lock().await;
                        let result = match resources.changes_since(last_seen_version).await {
                            Some(revisions) => send_revisions(
                                &sender,
                                &node_ownership,
                                &stream_node,
                                &subscribed,
                                &mut sent,
                                &mut nonces,
                                revisions,
                            ).await,
                            None => send_full_reconciliation(
                                &sender,
                                &resources,
                                &node_ownership,
                                &stream_node,
                                &subscribed,
                                &mut sent,
                                &mut nonces,
                                version,
                            ).await,
                        };
                        if result.is_err() {
                            break;
                        }
                        last_seen_version = version;
                    }
                    changed = ownership_receiver.changed() => {
                        if changed.is_err() {
                            break;
                        }
                        ownership_receiver.borrow_and_update();
                        let _guard = mutation_lock.lock().await;
                        let version = resources.current_version().await;
                        if send_visibility_reconciliation(
                            &sender,
                            &resources,
                            &node_ownership,
                            &stream_node,
                            &subscribed,
                            &mut sent,
                            &mut nonces,
                            version,
                        ).await.is_err() {
                            break;
                        }
                    }
                }
            }
            if let Some(session) = node_session {
                delivery
                    .lock()
                    .await
                    .close_node_session(&stream_node, session);
                let next_revision = (*delivery_notify.borrow()).saturating_add(1);
                delivery_notify.send_replace(next_revision);
            }
        });

        Ok(Response::new(
            Box::pin(ReceiverStream::new(receiver)) as DeltaStream
        ))
    }
}

async fn visible_snapshot(
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

async fn send_revisions(
    sender: &tokio::sync::mpsc::Sender<Result<DeltaDiscoveryResponse, Status>>,
    ownership: &NodeOwnershipRegistry,
    node: &str,
    subscribed: &HashSet<ResourceType>,
    sent: &mut HashMap<ResourceType, HashMap<String, ResourceOwner>>,
    nonces: &mut NonceTracker,
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
            if sender.send(Ok(response)).await.is_err() {
                return Err(());
            }
        }
    }
    Ok(())
}

async fn send_full_reconciliation(
    sender: &tokio::sync::mpsc::Sender<Result<DeltaDiscoveryResponse, Status>>,
    resources: &XdsResourceStore,
    ownership: &NodeOwnershipRegistry,
    node: &str,
    subscribed: &HashSet<ResourceType>,
    sent: &mut HashMap<ResourceType, HashMap<String, ResourceOwner>>,
    nonces: &mut NonceTracker,
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
        if sender.send(Ok(response)).await.is_err() {
            return Err(());
        }
    }
    Ok(())
}

async fn send_visibility_reconciliation(
    sender: &tokio::sync::mpsc::Sender<Result<DeltaDiscoveryResponse, Status>>,
    resources: &XdsResourceStore,
    ownership: &NodeOwnershipRegistry,
    node: &str,
    subscribed: &HashSet<ResourceType>,
    sent: &mut HashMap<ResourceType, HashMap<String, ResourceOwner>>,
    nonces: &mut NonceTracker,
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
        if sender.send(Ok(response)).await.is_err() {
            return Err(());
        }
    }
    Ok(())
}

fn snapshot_response(
    resource_type: ResourceType,
    version: u64,
    ownership_revision: u64,
    snapshot: Vec<ManagedXdsResource>,
    initial_resource_versions: &HashMap<String, String>,
    forced_sandboxes: &HashSet<SandboxId>,
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
    let mut removals = initial_resource_versions
        .keys()
        .filter(|name| !current.contains_key(*name))
        .cloned()
        .map(RemovedResource::client_only)
        .collect::<Vec<_>>();
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

fn delta_response(
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

#[cfg(test)]
mod tests {
    use super::*;
    use envoy_types::pb::google::protobuf::Any;

    #[test]
    fn nonce_tracker_is_bounded_and_consuming() {
        let owner = ResourceOwner::Sandbox(SandboxId::new());
        let mut tracker = NonceTracker::default();
        for index in 0..(NONCE_TRACK_LIMIT + 50) {
            tracker.insert(
                format!("nonce-{index}"),
                (
                    ResourceType::Listener,
                    index as u64,
                    vec![DeliveredResource {
                        name: format!("listener-{index}"),
                        owner,
                        removed: false,
                    }],
                ),
            );
        }
        assert!(tracker.entries.len() <= NONCE_TRACK_LIMIT);
        assert!(tracker.take("nonce-0").is_none());
        let recent = format!("nonce-{}", NONCE_TRACK_LIMIT + 49);
        assert!(tracker.take(&recent).is_some());
        assert!(tracker.take(&recent).is_none());
    }

    #[test]
    fn client_only_removals_are_not_attributed_to_delivery_attempts() {
        let mut tracker = NonceTracker::default();
        let (response, current) = snapshot_response(
            ResourceType::Listener,
            7,
            3,
            Vec::new(),
            &HashMap::from([("stale-listener".to_string(), "6".to_string())]),
            &HashSet::new(),
            &mut tracker,
        );

        assert!(current.is_empty());
        assert_eq!(response.removed_resources, vec!["stale-listener"]);
        let (_, _, delivered_resources) = tracker
            .take(&response.nonce)
            .expect("response nonce is tracked");
        assert!(delivered_resources.is_empty());
    }

    #[tokio::test]
    async fn node_move_removes_from_old_node_and_adds_to_new_node() {
        let resources = XdsResourceStore::new();
        let ownership = NodeOwnershipRegistry::node_scoped();
        let sandbox_id = SandboxId::new();
        let resource = ManagedXdsResource {
            name: "opaque-listener".to_string(),
            resource_type: ResourceType::Listener,
            owner: ResourceOwner::Sandbox(sandbox_id),
            payload: Any {
                type_url: ResourceType::Listener.type_url().to_string(),
                value: vec![1],
            },
        };
        resources
            .replace_inventory(vec![resource.clone()])
            .await
            .expect("seed resource world");
        ownership.assign(sandbox_id, "node-a");

        let (sender, mut receiver) = tokio::sync::mpsc::channel(4);
        let subscribed = HashSet::from([ResourceType::Listener]);
        let mut old_node_sent = HashMap::from([(
            ResourceType::Listener,
            HashMap::from([(resource.name.clone(), resource.owner)]),
        )]);
        let mut new_node_sent = HashMap::new();
        let mut old_node_nonces = NonceTracker::default();
        let mut new_node_nonces = NonceTracker::default();

        ownership.assign(sandbox_id, "node-b");
        send_visibility_reconciliation(
            &sender,
            &resources,
            &ownership,
            "node-a",
            &subscribed,
            &mut old_node_sent,
            &mut old_node_nonces,
            1,
        )
        .await
        .expect("old-node reconciliation");
        send_visibility_reconciliation(
            &sender,
            &resources,
            &ownership,
            "node-b",
            &subscribed,
            &mut new_node_sent,
            &mut new_node_nonces,
            1,
        )
        .await
        .expect("new-node reconciliation");

        let old_node = receiver.recv().await.expect("old-node response").unwrap();
        let new_node = receiver.recv().await.expect("new-node response").unwrap();
        assert_eq!(old_node.removed_resources, vec!["opaque-listener"]);
        assert!(old_node.resources.is_empty());
        assert_eq!(new_node.resources.len(), 1);
        assert_eq!(new_node.resources[0].name, "opaque-listener");
        assert!(new_node.removed_resources.is_empty());
    }
}
