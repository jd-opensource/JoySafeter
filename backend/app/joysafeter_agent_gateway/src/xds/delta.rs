//! Delta ADS transport over the authoritative resource and node registries.

use futures::Stream;
use std::collections::{HashMap, HashSet};
use std::pin::Pin;
use std::sync::Arc;
use tokio::sync::{watch, Mutex};
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status, Streaming};
use tracing::{debug, warn};

use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_server::AggregatedDiscoveryService, DeltaDiscoveryRequest,
    DeltaDiscoveryResponse, DiscoveryRequest, DiscoveryResponse,
};

use crate::ids::SandboxId;

use super::authority::{AuthorityPhase, RecoveryAuthorityGuard, XdsAuthority};
use super::delivery::{
    ApplyAdmission, DeliveryAttempt, DeliveryCoordinator, DeliveryRequest, DeliveryTarget,
    NodeSessionId, ReceiptOutcome, RemoveAdmission,
};
use super::inventory::RecoveryInventory;
use super::metrics::{XdsMetrics, XdsMetricsSnapshot, XdsStreamRejection};
use super::model::{ManagedXdsResource, ResourceOwner, ResourceType};
use super::node_health::EnvoyNodeHealthRegistry;
use super::node_ownership::{NodeOwnershipRegistry, OwnershipTransition};
use super::resource_store::{ManagedResourceChange, XdsResourceStore};

const RESOURCE_TYPES: [ResourceType; 2] = [ResourceType::Cluster, ResourceType::Listener];

type DeltaStream = Pin<Box<dyn Stream<Item = Result<DeltaDiscoveryResponse, Status>> + Send>>;
type SotwStream = Pin<Box<dyn Stream<Item = Result<DiscoveryResponse, Status>> + Send>>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RemovalDelivery {
    Superseded,
    Current(Option<DeliveryAttempt>),
}

pub struct DeltaXdsServer {
    resources: XdsResourceStore,
    node_ownership: NodeOwnershipRegistry,
    authority: XdsAuthority,
    mutation_lock: Arc<Mutex<()>>,
    delivery: Arc<Mutex<DeliveryCoordinator>>,
    delivery_notify: watch::Sender<u64>,
    metrics: XdsMetrics,
    node_health: EnvoyNodeHealthRegistry,
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
            node_health: EnvoyNodeHealthRegistry::default(),
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
        let admission = {
            let mut delivery = self.delivery.lock().await;
            delivery.admit_apply(&request)?
        };
        if let ApplyAdmission::Existing(attempt) = admission {
            return Ok(Some(attempt));
        }
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
    ) -> anyhow::Result<()> {
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
        delivery.replace_generation_watermarks(prepared.iter().map(|(request, _, _)| request));
        let mut deferred_count = 0usize;
        for (request, target, required_types) in prepared {
            if matches!(target, DeliveryTarget::Unavailable) {
                deferred_count = deferred_count.saturating_add(1);
                continue;
            }
            let attempt =
                delivery.begin_attempt(request.clone(), target.clone(), required_types.clone())?;
            delivery.mark_published(attempt, revision.version, required_types)?;
        }
        drop(delivery);
        self.notify_delivery_changed();
        self.metrics.set_degraded_inventory(deferred_count);

        Ok(())
    }

    /// Install a follower projection without granting ADS authority.
    /// Delivery watermarks are deliberately untouched; promotion rebuilds them
    /// under a fresh fenced recovery epoch.
    pub(crate) async fn install_replica_inventory(
        &self,
        resources: Vec<ManagedXdsResource>,
        assignments: HashMap<SandboxId, String>,
    ) -> anyhow::Result<()> {
        let _guard = self.mutation_lock.lock().await;
        self.node_ownership.replace_all(assignments);
        self.resources.replace_inventory(resources).await?;
        self.prune_node_health();
        Ok(())
    }

    pub(crate) async fn install_replica_sandbox(
        &self,
        sandbox_id: SandboxId,
        resources: Vec<ManagedXdsResource>,
    ) -> anyhow::Result<()> {
        let _guard = self.mutation_lock.lock().await;
        self.resources
            .replace_owner_resources(ResourceOwner::Sandbox(sandbox_id), resources)
            .await?;
        Ok(())
    }

    pub(crate) async fn remove_replica_sandbox(&self, sandbox_id: SandboxId) {
        let _guard = self.mutation_lock.lock().await;
        self.resources.remove_sandbox(sandbox_id).await;
        self.node_ownership.remove(sandbox_id);
        self.prune_node_health();
    }

    pub(crate) fn install_replica_placement(&self, sandbox_id: SandboxId, node: String) {
        self.node_ownership.assign(sandbox_id, node);
        self.prune_node_health();
    }

    pub(crate) fn remove_replica_placement(&self, sandbox_id: SandboxId) {
        self.node_ownership.remove(sandbox_id);
        self.prune_node_health();
    }

    pub(crate) async fn install_replica_placements(&self, assignments: HashMap<SandboxId, String>) {
        let _guard = self.mutation_lock.lock().await;
        self.node_ownership.replace_all(assignments);
        self.prune_node_health();
    }

    pub async fn remove_sandbox_resources(
        &self,
        sandbox_id: SandboxId,
        expected_generation: Option<super::model::DeliveryGeneration>,
        target: DeliveryTarget,
    ) -> anyhow::Result<RemovalDelivery> {
        let _guard = self.mutation_lock.lock().await;
        let admission = self
            .delivery
            .lock()
            .await
            .admit_remove(sandbox_id, expected_generation.as_ref())?;
        if matches!(admission, RemoveAdmission::Superseded) {
            return Ok(RemovalDelivery::Superseded);
        }
        if matches!(admission, RemoveAdmission::AlreadyRemoved) {
            return Ok(RemovalDelivery::Current(None));
        }
        let required_types = self
            .resources
            .resources_owned_by(ResourceOwner::Sandbox(sandbox_id))
            .await
            .into_iter()
            .map(|resource| resource.resource_type)
            .collect::<HashSet<_>>();
        if required_types.is_empty() {
            self.delivery
                .lock()
                .await
                .mark_removed(sandbox_id, expected_generation.as_ref());
            return Ok(RemovalDelivery::Current(None));
        }
        let mut delivery = self.delivery.lock().await;
        let request = delivery
            .current_request(sandbox_id)
            .ok_or(super::delivery::DeliveryError::MissingDeliveryContext)?;
        self.authority
            .validate_delivery_epoch(request.authority_epoch)?;
        if matches!(target, DeliveryTarget::Unavailable) {
            let revision = self.resources.remove_sandbox(sandbox_id).await;
            delivery.mark_removed(sandbox_id, expected_generation.as_ref());
            delivery.forget(sandbox_id);
            drop(delivery);
            if !revision.changes.is_empty() {
                self.notify_delivery_changed();
            }
            return Ok(RemovalDelivery::Current(None));
        }
        let attempt = delivery.begin_removal(sandbox_id, target, required_types.clone())?;
        let revision = self.resources.remove_sandbox(sandbox_id).await;
        delivery.mark_removed(sandbox_id, expected_generation.as_ref());
        delivery.mark_published(attempt, revision.version, required_types)?;
        drop(delivery);
        self.notify_delivery_changed();
        Ok(RemovalDelivery::Current(Some(attempt)))
    }

    pub async fn assign_sandbox_node(
        &self,
        sandbox_id: SandboxId,
        node: impl Into<String>,
    ) -> anyhow::Result<Option<DeliveryAttempt>> {
        let _guard = self.mutation_lock.lock().await;
        let transition = self.node_ownership.assign(sandbox_id, node);
        self.record_ownership_transition(&transition);
        self.prune_node_health();
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
        self.prune_node_health();
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
        self.prune_node_health();
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
        self.metrics.snapshot(
            self.authority.metrics_snapshot(),
            delivery,
            self.node_health.snapshot(),
        )
    }

    fn record_ownership_transition(&self, transition: &OwnershipTransition) {
        match transition {
            OwnershipTransition::Assigned { .. } => self.metrics.record_ownership_assigned(),
            OwnershipTransition::Moved { .. } => self.metrics.record_ownership_moved(),
            OwnershipTransition::Removed { .. } => self.metrics.record_ownership_removed(),
            OwnershipTransition::Unchanged { .. } | OwnershipTransition::Missing { .. } => {}
        }
    }

    fn prune_node_health(&self) {
        self.node_health
            .retain_connected_or_assigned(&self.node_ownership.assigned_node_names());
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
        let node_health = self.node_health.clone();
        let mut resource_receiver = resources.subscribe();
        let mut ownership_receiver = node_ownership.subscribe();

        tokio::spawn(async move {
            let mut stream_node = String::new();
            let mut node_session = None::<NodeSessionId>;
            let mut nonces = NonceTracker::default();
            let mut subscribed = HashSet::<ResourceType>::new();
            let mut sent = HashMap::<ResourceType, HashMap<String, ResourceOwner>>::new();
            // A newly elected leader starts with an empty disposable projection.
            // Preserve Envoy's last-good resources while the Orchestrator replays
            // policy, then reconcile this inventory once recovery is complete.
            let mut deferred_initial_versions =
                HashMap::<ResourceType, HashMap<String, String>>::new();
            let mut last_seen_version = *resource_receiver.borrow_and_update();

            loop {
                tokio::select! {
                    biased;
                    changed = authority_receiver.changed() => {
                        if changed.is_err() {
                            debug!("xDS authority watcher closed; closing ADS stream");
                            break;
                        }
                        let phase = *authority_receiver.borrow_and_update();
                        if !phase.serves_ads() {
                            debug!("xDS authority revoked; closing ADS stream");
                            break;
                        }
                        if matches!(phase, AuthorityPhase::Ready { .. })
                            && !deferred_initial_versions.is_empty()
                        {
                            let Some(session) = node_session else {
                                continue;
                            };
                            // Build all deferred snapshots under the lock, then flush
                            // without it so a slow reader cannot stall others. (H1)
                            let responses = {
                                let _guard = mutation_lock.lock().await;
                                let version = resources.current_version().await;
                                let mut responses = Vec::new();
                                for resource_type in RESOURCE_TYPES {
                                    let Some(initial_versions) =
                                        deferred_initial_versions.remove(&resource_type)
                                    else {
                                        continue;
                                    };
                                    let snapshot = visible_snapshot(
                                        &resources,
                                        &node_ownership,
                                        resource_type,
                                        &stream_node,
                                    )
                                    .await;
                                    let forced_sandboxes = delivery
                                        .lock()
                                        .await
                                        .pending_sandboxes_for(&stream_node, resource_type);
                                    let (response, current) = snapshot_response(
                                        resource_type,
                                        version,
                                        node_ownership.current_revision(),
                                        snapshot,
                                        &initial_versions,
                                        &forced_sandboxes,
                                        true,
                                        &mut nonces,
                                    );
                                    sent.insert(resource_type, current);
                                    responses.push(response);
                                }
                                (version, responses)
                            };
                            let (version, responses) = responses;
                            if flush_responses(
                                &sender,
                                &node_health,
                                &stream_node,
                                session,
                                responses,
                            )
                            .await
                            .is_err()
                            {
                                break;
                            }
                            last_seen_version = version;
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
                            node_health.connect(
                                &stream_node,
                                node_session.expect("node session was just established"),
                            );
                            metrics.record_node_stream_connection();
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
                                if request.error_detail.is_some() {
                                    node_health.reject(
                                        &stream_node,
                                        session,
                                        resource_type,
                                        &request.response_nonce,
                                    );
                                } else {
                                    if node_health.acknowledge(
                                        &stream_node,
                                        session,
                                        resource_type,
                                        &request.response_nonce,
                                    ) {
                                        metrics.record_node_ready_transition();
                                    }
                                }
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
                                            let reason = sanitize_xds_nack(&error.message);
                                            warn!(code = error.code, reason = %reason, "Envoy NACK'd xDS update");
                                            let outcome = coordinator.reject(
                                                &stream_node,
                                                session,
                                                &request.response_nonce,
                                                reason,
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
                            let response = {
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
                                let recovery_serving = matches!(
                                    *authority_receiver.borrow(),
                                    AuthorityPhase::RecoveryServing { .. }
                                );
                                if recovery_serving {
                                    deferred_initial_versions.insert(
                                        resource_type,
                                        request.initial_resource_versions.clone(),
                                    );
                                }
                                let (response, current) = snapshot_response(
                                    resource_type,
                                    version,
                                    node_ownership.current_revision(),
                                    snapshot,
                                    &request.initial_resource_versions,
                                    &forced_sandboxes,
                                    !recovery_serving,
                                    &mut nonces,
                                );
                                if !request.initial_resource_versions.is_empty() {
                                    metrics.record_reconnect(
                                        response.resources.len(),
                                        response.removed_resources.len(),
                                    );
                                }
                                sent.insert(resource_type, current);
                                response
                            };
                            // Flush without the mutation lock so a slow reader cannot
                            // stall other sandboxes' publish/remove/recovery. (H1)
                            let session = node_session.expect("node session established with node id");
                            if flush_responses(
                                &sender,
                                &node_health,
                                &stream_node,
                                session,
                                vec![response],
                            )
                            .await
                            .is_err()
                            {
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
                        // The stream may not have identified yet (no inbound request
                        // seen). The version change is already consumed above, so it
                        // is safe to skip until the node id is known. (Fixes C4.)
                        let Some(session) = node_session else {
                            continue;
                        };
                        // Build responses under the mutation lock, then release it
                        // before flushing to the (bounded) stream channel so a slow
                        // Envoy reader cannot stall other sandboxes. (Fixes H1.)
                        let responses = {
                            let _guard = mutation_lock.lock().await;
                            match resources.changes_since(last_seen_version).await {
                                Some(revisions) => build_revisions(
                                    &node_ownership,
                                    &stream_node,
                                    &subscribed,
                                    &mut sent,
                                    &mut nonces,
                                    revisions,
                                ),
                                None => {
                                    metrics.record_full_reconciliation();
                                    build_full_reconciliation(
                                        &resources,
                                        &node_ownership,
                                        &stream_node,
                                        &subscribed,
                                        &mut sent,
                                        &mut nonces,
                                        version,
                                    )
                                    .await
                                }
                            }
                        };
                        if flush_responses(&sender, &node_health, &stream_node, session, responses)
                            .await
                            .is_err()
                        {
                            break;
                        }
                        last_seen_version = version;
                    }
                    changed = ownership_receiver.changed() => {
                        if changed.is_err() {
                            break;
                        }
                        ownership_receiver.borrow_and_update();
                        let Some(session) = node_session else {
                            continue;
                        };
                        let responses = {
                            let _guard = mutation_lock.lock().await;
                            let version = resources.current_version().await;
                            build_visibility_reconciliation(
                                &resources,
                                &node_ownership,
                                &stream_node,
                                &subscribed,
                                &mut sent,
                                &mut nonces,
                                version,
                            )
                            .await
                        };
                        if flush_responses(&sender, &node_health, &stream_node, session, responses)
                            .await
                            .is_err()
                        {
                            break;
                        }
                    }
                }
            }
            if let Some(session) = node_session {
                if node_health.disconnect(&stream_node, session) {
                    metrics.record_node_stream_disconnect();
                }
                node_health.retain_connected_or_assigned(&node_ownership.assigned_node_names());
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

mod reconciliation;
mod response;

use reconciliation::{
    build_full_reconciliation, build_revisions, build_visibility_reconciliation, flush_responses,
    visible_snapshot,
};
use response::{sanitize_xds_nack, snapshot_response, NonceTracker};

#[cfg(test)]
#[path = "../../tests/unit/xds/delta_test.rs"]
mod tests;
