//! Envoy Delta ADS transport.
//!
//! This module owns authenticated ADS streams, nonce/subscription handling and
//! protobuf responses. Resource publication lives in [`super::publisher`], while
//! filesystem delivery lives in [`crate::sandbox::envoy_delivery`].

use std::collections::{HashMap, HashSet};
use std::pin::Pin;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex as StdMutex};
use std::time::Duration;

use futures::Stream;
use tokio::sync::watch;
use tokio_stream::wrappers::ReceiverStream;
use tonic::{Request, Response, Status, Streaming};
use tracing::{debug, warn};
#[cfg(test)]
use uuid::Uuid;

use crate::ids::SandboxId;
#[cfg(test)]
use crate::kernel::network_policy::envoy_model::{
    escape_envoy_header_value, proxy_authorization_value, rendered_egress_policy_summary,
    validate_egress_policy, EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping,
    EgressPathMatcher, EgressRetryMode, ListenerKind, SandboxCredentials, SandboxEgressPolicy,
    EXTERNAL_EGRESS_HOST, LLM_EGRESS_HOST, MCP_EGRESS_HOST,
};
#[cfg(test)]
use crate::kernel::network_policy::envoy_model::{ClusterSpec, ListenerSpec};
#[cfg(test)]
use crate::sandbox::envoy_render::LISTENER_TYPE_URL;
#[cfg(test)]
use crate::sandbox::envoy_render::{encode_cluster_any, encode_listener_any};
use crate::xds::ack_tracker::{AckDisposition, AckRecordOutcome, ApplyStatus};
use crate::xds::auth::{AdsAuthenticator, StaticTokenAdsAuthenticator};
#[cfg(test)]
use crate::xds::control_plane::sandbox_id_from_resource_name;
use crate::xds::control_plane::XdsControlPlane;
#[cfg(test)]
use crate::xds::inventory::XdsResource;
use crate::xds::inventory::{InventoryMutation, VersionedResourceChange};
use crate::xds::metrics::XdsMetrics;
use crate::xds::model::{NodeId, PlacementRevision, ResourceType, StreamId};

use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_server::AggregatedDiscoveryService, DeltaDiscoveryRequest,
    DeltaDiscoveryResponse, DiscoveryRequest, DiscoveryResponse, Resource,
};
use envoy_types::pb::google::protobuf::Any;

// ===========================================================================
// gRPC (Delta ADS) backend
// ===========================================================================

const XDS_NONCE_TRACK_LIMIT: usize = 512;

#[derive(Clone)]
struct NonceContext {
    resource_type: ResourceType,
    resource_version: u64,
    placement_revision: PlacementRevision,
    resource_names: Vec<String>,
}

#[derive(Default)]
struct NonceTracker {
    map: HashMap<String, NonceContext>,
    order: std::collections::VecDeque<String>,
}

impl NonceTracker {
    fn insert(&mut self, nonce: String, entry: NonceContext) {
        if self.map.insert(nonce.clone(), entry).is_none() {
            self.order.push_back(nonce);
        }
        while self.order.len() > XDS_NONCE_TRACK_LIMIT {
            if let Some(old) = self.order.pop_front() {
                self.map.remove(&old);
            }
        }
    }

    fn take(&mut self, nonce: &str) -> Option<NonceContext> {
        let entry = self.map.remove(nonce);
        if entry.is_some() {
            self.order.retain(|tracked| tracked != nonce);
        }
        entry
    }
}

/// Delta ADS gRPC service hosted by the dedicated xDS server/port. Envoy
/// connects and receives incremental CDS + LDS updates on one aggregated stream.
pub struct DeltaXdsServer {
    authenticator: Arc<dyn AdsAuthenticator>,
    metrics: Arc<XdsMetrics>,
    control_plane: Arc<StdMutex<XdsControlPlane>>,
    /// Bumped on every state change to wake the active Delta stream.
    notify: watch::Sender<u64>,
    /// Bumped when sandbox ownership changes so every connected node can
    /// reconcile its audience independently from resource content versions.
    placement_notify: watch::Sender<u64>,
    /// Whether this process may serve ADS. Standalone starts enabled; K8s
    /// multi-replica coordination disables it until authority recovery finishes.
    serving: watch::Sender<bool>,
    status_notify: watch::Sender<u64>,
    next_stream_id: AtomicU64,
}

impl DeltaXdsServer {
    pub fn new(authenticator: Arc<dyn AdsAuthenticator>) -> Arc<Self> {
        Self::with_metrics(authenticator, Arc::new(XdsMetrics::default()))
    }

    pub fn with_metrics(
        authenticator: Arc<dyn AdsAuthenticator>,
        metrics: Arc<XdsMetrics>,
    ) -> Arc<Self> {
        let (notify, _rx) = watch::channel(0u64);
        let (placement_notify, _placement_rx) = watch::channel(0u64);
        let (serving, _serving_rx) = watch::channel(true);
        let (status_notify, _status_rx) = watch::channel(0u64);
        Arc::new(Self {
            authenticator,
            metrics,
            control_plane: Arc::new(StdMutex::new(XdsControlPlane::standalone())),
            notify,
            placement_notify,
            serving,
            status_notify,
            next_stream_id: AtomicU64::new(1),
        })
    }

    pub fn metrics(&self) -> Arc<XdsMetrics> {
        self.metrics.clone()
    }

    pub fn with_static_token(token: impl AsRef<str>) -> anyhow::Result<Arc<Self>> {
        Ok(Self::new(Arc::new(StaticTokenAdsAuthenticator::new(
            token,
        )?)))
    }

    /// Enable or disable ADS serving. Disabling wakes every active stream so a
    /// former authority cannot retain long-lived Envoy connections after its
    /// leader-only Service endpoint is removed.
    pub fn set_serving(&self, serving: bool) {
        if !serving && *self.serving.borrow() {
            self.control_plane
                .lock()
                .expect("xDS control-plane lock poisoned")
                .revoke_authority();
            self.bump_status_notify();
        }
        self.serving.send_replace(serving);
    }

    pub fn is_serving(&self) -> bool {
        *self.serving.borrow()
    }

    pub fn enable_node_aware(&self) {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .enable_node_aware();
    }

    pub fn begin_authority_epoch(&self, epoch: crate::xds::model::AuthorityEpoch) {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .begin_authority_epoch(epoch);
        self.bump_status_notify();
    }

    /// Register which K8s node a sandbox is running on. Stream tasks use this
    /// to filter resources — only sending listeners for sandboxes on their node.
    /// In standalone/Docker mode this is not called; the filter defaults to
    /// "include all" when a sandbox has no node entry.
    pub fn set_sandbox_node(&self, sandbox_id: SandboxId, node_name: String) {
        let Ok(node_id) = NodeId::new(node_name) else {
            warn!(%sandbox_id, "ignoring invalid xDS placement node id");
            return;
        };
        let delta = self
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .assign_node(sandbox_id, node_id);
        if !delta.upserts().is_empty() || !delta.removals().is_empty() {
            self.placement_notify.send_replace(delta.revision().get());
            self.bump_status_notify();
        }
    }

    /// Remove sandbox→node mapping (called on sandbox destroy).
    pub fn remove_sandbox_node(&self, sandbox_id: SandboxId) {
        let delta = self
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .remove_node(sandbox_id);
        if let Some(delta) = delta {
            self.placement_notify.send_replace(delta.revision().get());
            self.bump_status_notify();
        }
    }

    pub(super) async fn wait_for_sandbox_ack(
        &self,
        sandbox_id: SandboxId,
        timeout: Duration,
    ) -> anyhow::Result<()> {
        let mut rx = self.status_notify.subscribe();
        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            let status = self
                .control_plane
                .lock()
                .expect("xDS control-plane lock poisoned")
                .apply_status(sandbox_id);
            match status {
                Some(ApplyStatus::Acked) => return Ok(()),
                Some(ApplyStatus::Nacked(reason)) => {
                    anyhow::bail!("Envoy NACK'd xDS update for sandbox {sandbox_id}: {reason}")
                }
                Some(ApplyStatus::Pending { .. }) | None => {}
            }
            let now = tokio::time::Instant::now();
            if now >= deadline {
                anyhow::bail!("timed out waiting for Envoy xDS ACK for sandbox {sandbox_id}");
            }
            if tokio::time::timeout_at(deadline, rx.changed())
                .await
                .is_err()
            {
                anyhow::bail!("timed out waiting for Envoy xDS ACK for sandbox {sandbox_id}");
            }
        }
    }

    /// Drop retained ACK/NACK state for a torn-down sandbox.
    pub(super) async fn forget_sandbox(&self, sandbox_id: SandboxId) {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .forget_sandbox(sandbox_id);
        self.bump_status_notify();
    }

    /// Apply a batch of changes to one resource type and wake the stream.
    pub(super) async fn apply(
        &self,
        resource_type: ResourceType,
        changes: Vec<InventoryMutation>,
        pending_sandboxes: Vec<SandboxId>,
    ) -> u64 {
        self.apply_batch(vec![(resource_type, changes)], pending_sandboxes)
            .await
    }

    /// Apply changes across several resource types as one atomic update: a single
    /// version tick, one change-log group per non-empty type (in the given order,
    /// so callers pass Clusters before Listeners for make-before-break), and one
    /// `notify` wake. This lets a sandbox's CDS + LDS update ride a single version
    /// instead of two, halving stream wakeups and re-pushes under load.
    pub(super) async fn apply_batch(
        &self,
        groups: Vec<(ResourceType, Vec<InventoryMutation>)>,
        pending_sandboxes: Vec<SandboxId>,
    ) -> u64 {
        let previous_version = *self.notify.borrow();
        let version = self
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .apply_batch(groups, pending_sandboxes)
            .version();
        if version != previous_version {
            self.notify.send_replace(version);
            self.bump_status_notify();
        }
        version
    }

    pub(super) fn resource_names(&self, resource_type: ResourceType) -> Vec<String> {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .snapshot_type(resource_type)
            .into_keys()
            .collect()
    }

    pub(super) fn resource_names_with_prefix(
        &self,
        resource_type: ResourceType,
        prefix: &str,
    ) -> Vec<String> {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .resources_with_prefix(resource_type, prefix)
            .into_iter()
            .map(|resource| resource.name().to_string())
            .collect()
    }

    pub(super) fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .configured_sandbox_ids()
    }

    fn bump_status_notify(&self) {
        let next = {
            let current = self.status_notify.borrow();
            (*current).saturating_add(1)
        };
        self.status_notify.send_replace(next);
    }
}
type DeltaStream = Pin<Box<dyn Stream<Item = Result<DeltaDiscoveryResponse, Status>> + Send>>;
type SotwStream = Pin<Box<dyn Stream<Item = Result<DiscoveryResponse, Status>> + Send>>;

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
        let authenticated_node = match self.authenticator.authenticate(request.metadata()) {
            Ok(node) => node.node_id().clone(),
            Err(status) => {
                self.metrics.authentication_failed();
                return Err(status);
            }
        };
        let mut serving_rx = self.serving.subscribe();
        if !*serving_rx.borrow_and_update() {
            return Err(Status::unavailable("xDS authority is not ready"));
        }

        let mut inbound = request.into_inner();
        let (tx, rx) = tokio::sync::mpsc::channel::<Result<DeltaDiscoveryResponse, Status>>(16);
        let mut notify_rx = self.notify.subscribe();
        let mut placement_rx = self.placement_notify.subscribe();
        let control_plane = self.control_plane_handle();
        let metrics = self.metrics.clone();
        let stream_id = StreamId::new(self.next_stream_id.fetch_add(1, Ordering::Relaxed));
        control_plane.register_stream(authenticated_node.clone(), stream_id);
        metrics.stream_opened();

        const TYPES: [ResourceType; 2] = [ResourceType::Cluster, ResourceType::Listener];

        let task = async move {
            let mut stream_node: Option<NodeId> = None;
            let mut nonce_resources = NonceTracker::default();
            let mut subscribed = HashSet::<ResourceType>::new();
            let mut sent = HashMap::<ResourceType, HashSet<String>>::new();
            let mut last_seen_version = *notify_rx.borrow_and_update();

            loop {
                tokio::select! {
                    biased;
                    changed = serving_rx.changed() => {
                        if changed.is_err() || !*serving_rx.borrow_and_update() {
                            debug!("xDS authority revoked; closing ADS stream");
                            break;
                        }
                    }
                    message = inbound.message() => {
                        match message {
                            Ok(Some(request)) => {
                                debug!(
                                    type_url = %request.type_url,
                                    response_nonce = %request.response_nonce,
                                    has_error = request.error_detail.is_some(),
                                    subscribe_count = request.resource_names_subscribe.len(),
                                    unsubscribe_count = request.resource_names_unsubscribe.len(),
                                    "Received Envoy Delta ADS request"
                                );
                                if let Some(ref node) = request.node {
                                    let Ok(claimed_node) = NodeId::new(&node.id) else {
                                        let _ = tx.send(Err(Status::unauthenticated("ADS request is missing a valid node.id"))).await;
                                        break;
                                    };
                                    if claimed_node != authenticated_node {
                                        let _ = tx.send(Err(Status::permission_denied("ADS node.id does not match authenticated node"))).await;
                                        break;
                                    }
                                    if stream_node.as_ref().is_some_and(|current| current != &claimed_node) {
                                        let _ = tx.send(Err(Status::permission_denied("ADS stream node.id changed"))).await;
                                        break;
                                    }
                                    if stream_node.is_none() {
                                        debug!(node_id = %claimed_node, stream_id = stream_id.get(), "xDS stream identified authenticated node");
                                        stream_node = Some(claimed_node);
                                    }
                                } else if stream_node.is_none() {
                                    let _ = tx.send(Err(Status::unauthenticated("ADS initial request must include node.id"))).await;
                                    break;
                                }

                                if !request.response_nonce.is_empty() {
                                    let tracked = nonce_resources.take(&request.response_nonce);
                                    debug!(
                                        nonce = %request.response_nonce,
                                        tracked = tracked.is_some(),
                                        "Resolved Envoy Delta ADS response nonce"
                                    );
                                    if let Some(context) = tracked {
                                        let node_id = stream_node.as_ref().expect("validated ADS node");
                                        let disposition = if let Some(error) = &request.error_detail {
                                            warn!(code = error.code, message = %error.message, nonce = %request.response_nonce, "Envoy NACK'd xDS update");
                                            AckDisposition::Nack(error.message.clone())
                                        } else {
                                            AckDisposition::Ack
                                        };
                                        control_plane.record_response(
                                            &context.resource_names,
                                            context.resource_version,
                                            context.placement_revision,
                                            node_id,
                                            stream_id,
                                            context.resource_type,
                                            disposition,
                                        );
                                    }
                                }

                                let Some(resource_type) = ResourceType::from_type_url(&request.type_url) else {
                                    continue;
                                };
                                if TYPES.contains(&resource_type) && subscribed.insert(resource_type) {
                                    let node_id = stream_node.as_ref().expect("validated ADS node");
                                    let (version, placement_revision, snapshot) =
                                        control_plane.version_and_snapshot(resource_type, node_id);
                                    let (response, current) = delta_response_from_snapshot(
                                        resource_type,
                                        version,
                                        placement_revision,
                                        snapshot,
                                        &mut nonce_resources,
                                    );
                                    sent.insert(resource_type, current);
                                    debug!(
                                        type_url = %response.type_url,
                                        version,
                                        resources = response.resources.len(),
                                        removed = response.removed_resources.len(),
                                        nonce = %response.nonce,
                                        "Sending Envoy Delta ADS snapshot"
                                    );
                                    if tx.send(Ok(response)).await.is_err() {
                                        break;
                                    }
                                }
                            }
                            Err(error) => {
                                debug!(error = %error, "xDS inbound stream error, closing");
                                break;
                            }
                            Ok(None) => {
                                debug!("Envoy closed xDS stream");
                                break;
                            }
                        }
                    }
                    changed = notify_rx.changed() => {
                        if changed.is_err() {
                            break;
                        }
                        let version = *notify_rx.borrow_and_update();
                        if version == last_seen_version {
                            continue;
                        }
                        let node_id = stream_node.as_ref().expect("validated ADS node");
                        let placement_revision = control_plane.placement_revision();
                        let Some(changes) = control_plane.changes_since_for_node(last_seen_version, node_id) else {
                            let mut closed = false;
                            for resource_type in TYPES {
                                if !subscribed.contains(&resource_type) {
                                    continue;
                                }
                                let (snapshot_version, snapshot_placement, snapshot) =
                                    control_plane.version_and_snapshot(resource_type, node_id);
                                let (response, current) = delta_response_from_snapshot(
                                    resource_type,
                                    snapshot_version,
                                    snapshot_placement,
                                    snapshot,
                                    &mut nonce_resources,
                                );
                                sent.insert(resource_type, current);
                                if tx.send(Ok(response)).await.is_err() {
                                    closed = true;
                                    break;
                                }
                            }
                            if closed {
                                break;
                            }
                            last_seen_version = version;
                            continue;
                        };

                        let mut closed = false;
                        for change in changes {
                            if !subscribed.contains(&change.resource_type()) {
                                continue;
                            }
                            let (response, removed) = delta_response_from_change(
                                change,
                                placement_revision,
                                &mut nonce_resources,
                            );
                            let previous = sent.entry(
                                ResourceType::from_type_url(&response.type_url)
                                    .expect("domain resource type has a known type URL"),
                            ).or_default();
                            for resource in &response.resources {
                                previous.insert(resource.name.clone());
                            }
                            for name in &removed {
                                previous.remove(name);
                            }
                            if response.resources.is_empty() && response.removed_resources.is_empty() {
                                continue;
                            }
                            debug!(
                                type_url = %response.type_url,
                                version,
                                resources = response.resources.len(),
                                removed = response.removed_resources.len(),
                                nonce = %response.nonce,
                                "Sending Envoy Delta ADS update"
                            );
                            if tx.send(Ok(response)).await.is_err() {
                                closed = true;
                                break;
                            }
                        }
                        if closed {
                            break;
                        }
                        last_seen_version = version;
                    }
                    changed = placement_rx.changed() => {
                        if changed.is_err() {
                            break;
                        }
                        let node_id = stream_node.as_ref().expect("validated ADS node");
                        let mut closed = false;
                        for resource_type in TYPES {
                            if !subscribed.contains(&resource_type) {
                                continue;
                            }
                            let (version, placement_revision, snapshot) =
                                control_plane.version_and_snapshot(resource_type, node_id);
                            let previous = sent.entry(resource_type).or_default();
                            let response = delta_response_from_audience_snapshot(
                                resource_type,
                                version,
                                placement_revision,
                                snapshot,
                                previous,
                                &mut nonce_resources,
                            );
                            if response.resources.is_empty() && response.removed_resources.is_empty() {
                                continue;
                            }
                            if tx.send(Ok(response)).await.is_err() {
                                closed = true;
                                break;
                            }
                        }
                        if closed {
                            break;
                        }
                    }
                }
            }
            control_plane.unregister_stream(&authenticated_node, stream_id);
            metrics.stream_closed();
        };
        tokio::spawn(task);

        Ok(Response::new(
            Box::pin(ReceiverStream::new(rx)) as DeltaStream
        ))
    }
}

#[derive(Clone)]
struct ControlPlaneHandle {
    control_plane: Arc<StdMutex<XdsControlPlane>>,
    status_notify: watch::Sender<u64>,
    metrics: Arc<XdsMetrics>,
}

impl ControlPlaneHandle {
    fn register_stream(&self, node_id: NodeId, stream_id: StreamId) {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .register_stream(node_id, stream_id);
        self.bump_status_notify();
    }

    fn unregister_stream(&self, node_id: &NodeId, stream_id: StreamId) {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .unregister_stream(node_id, stream_id);
    }

    fn record_response(
        &self,
        resources: &[String],
        version: u64,
        placement_revision: PlacementRevision,
        node_id: &NodeId,
        stream_id: StreamId,
        resource_type: ResourceType,
        disposition: AckDisposition,
    ) {
        let outcomes = self
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .record_response(
                resources,
                version,
                placement_revision,
                node_id,
                stream_id,
                resource_type,
                disposition,
            );
        let acknowledged = outcomes.iter().any(|outcome| {
            matches!(
                outcome,
                AckRecordOutcome::Pending | AckRecordOutcome::Converged
            )
        });
        let nacked = outcomes
            .iter()
            .any(|outcome| matches!(outcome, AckRecordOutcome::Nacked(_)));
        if acknowledged || nacked {
            if acknowledged {
                self.metrics.ack_recorded();
            }
            if nacked {
                self.metrics.nack_recorded();
            }
            self.bump_status_notify();
        }
    }

    fn version_and_snapshot(
        &self,
        resource_type: ResourceType,
        node_id: &NodeId,
    ) -> (
        u64,
        PlacementRevision,
        std::collections::BTreeMap<String, prost_types::Any>,
    ) {
        let control_plane = self
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned");
        (
            control_plane.version(),
            control_plane.placement_revision(),
            control_plane.snapshot_for_node(resource_type, node_id),
        )
    }

    fn changes_since_for_node(
        &self,
        version: u64,
        node_id: &NodeId,
    ) -> Option<Vec<VersionedResourceChange>> {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .changes_since_for_node(version, node_id)
    }

    fn placement_revision(&self) -> PlacementRevision {
        self.control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .placement_revision()
    }

    fn bump_status_notify(&self) {
        let next = {
            let current = self.status_notify.borrow();
            (*current).saturating_add(1)
        };
        self.status_notify.send_replace(next);
    }
}

fn delta_response_from_snapshot(
    resource_type: ResourceType,
    version: u64,
    placement_revision: PlacementRevision,
    snapshot: std::collections::BTreeMap<String, prost_types::Any>,
    nonce_resources: &mut NonceTracker,
) -> (DeltaDiscoveryResponse, HashSet<String>) {
    let type_url = resource_type.type_url().to_string();
    let current = snapshot.keys().cloned().collect::<HashSet<_>>();
    let resources = snapshot
        .into_iter()
        .map(|(name, any)| Resource {
            name,
            version: version.to_string(),
            resource: Some(wire_any(any)),
            ..Default::default()
        })
        .collect::<Vec<_>>();
    let nonce = format!("n-{type_url}-{version}-snapshot");
    nonce_resources.insert(
        nonce.clone(),
        NonceContext {
            resource_type,
            resource_version: version,
            placement_revision,
            resource_names: resources
                .iter()
                .map(|resource| resource.name.clone())
                .collect(),
        },
    );
    (
        DeltaDiscoveryResponse {
            system_version_info: version.to_string(),
            resources,
            removed_resources: vec![],
            type_url,
            nonce,
            ..Default::default()
        },
        current,
    )
}

fn delta_response_from_audience_snapshot(
    resource_type: ResourceType,
    resource_version: u64,
    placement_revision: PlacementRevision,
    snapshot: std::collections::BTreeMap<String, prost_types::Any>,
    previous: &mut HashSet<String>,
    nonce_resources: &mut NonceTracker,
) -> DeltaDiscoveryResponse {
    let type_url = resource_type.type_url();
    let current = snapshot.keys().cloned().collect::<HashSet<_>>();
    let removed_resources = previous.difference(&current).cloned().collect::<Vec<_>>();
    let resources = snapshot
        .into_iter()
        .map(|(name, resource)| Resource {
            name,
            version: resource_version.to_string(),
            resource: Some(wire_any(resource)),
            ..Default::default()
        })
        .collect::<Vec<_>>();
    let nonce = format!(
        "n-{type_url}-{resource_version}-placement-{}",
        placement_revision.get()
    );
    nonce_resources.insert(
        nonce.clone(),
        NonceContext {
            resource_type,
            resource_version,
            placement_revision,
            resource_names: resources
                .iter()
                .map(|resource| resource.name.clone())
                .chain(removed_resources.iter().cloned())
                .collect(),
        },
    );
    *previous = current;
    DeltaDiscoveryResponse {
        system_version_info: resource_version.to_string(),
        resources,
        removed_resources,
        type_url: type_url.to_string(),
        nonce,
        ..Default::default()
    }
}

fn delta_response_from_change(
    change: VersionedResourceChange,
    placement_revision: PlacementRevision,
    nonce_resources: &mut NonceTracker,
) -> (DeltaDiscoveryResponse, Vec<String>) {
    let mut removed = Vec::new();
    let mut resources = Vec::new();
    for item in change.mutations() {
        match item {
            InventoryMutation::Upsert(resource) => {
                resources.push(Resource {
                    name: resource.name().to_string(),
                    version: change.version().to_string(),
                    resource: Some(wire_any(resource.payload().clone())),
                    ..Default::default()
                });
            }
            InventoryMutation::Remove { name, .. } => {
                removed.push(name.clone());
            }
        }
    }
    let resource_type = change.resource_type();
    let type_url = resource_type.type_url().to_string();
    let version = change.version();
    let nonce = format!("n-{type_url}-{version}");
    nonce_resources.insert(
        nonce.clone(),
        NonceContext {
            resource_type,
            resource_version: version,
            placement_revision,
            resource_names: resources
                .iter()
                .map(|resource| resource.name.clone())
                .chain(removed.iter().cloned())
                .collect(),
        },
    );
    (
        DeltaDiscoveryResponse {
            system_version_info: version.to_string(),
            resources,
            removed_resources: removed.clone(),
            type_url,
            nonce,
            ..Default::default()
        },
        removed,
    )
}

impl DeltaXdsServer {
    fn control_plane_handle(&self) -> ControlPlaneHandle {
        ControlPlaneHandle {
            control_plane: self.control_plane.clone(),
            status_notify: self.status_notify.clone(),
            metrics: self.metrics.clone(),
        }
    }
}

fn wire_any(any: prost_types::Any) -> Any {
    Any {
        type_url: any.type_url,
        value: any.value,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sandbox::envoy_delivery::LdsBackend;
    use crate::sandbox::envoy_render::json::build_virtual_hosts_json;
    use crate::sandbox::envoy_render::proto::build_virtual_hosts_proto;
    use crate::sandbox::envoy_render::{render_cluster_json, render_listener_json};
    use crate::xds::publisher::GrpcLds;
    use envoy_types::pb::envoy::service::discovery::v3::{
        aggregated_discovery_service_client::AggregatedDiscoveryServiceClient,
        aggregated_discovery_service_server::AggregatedDiscoveryServiceServer,
    };
    use prost::Message;
    use serde_json::json;
    use tokio::net::TcpListener;
    use tokio::sync::oneshot;
    use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
    use tonic::transport::Server;

    fn test_server() -> Arc<DeltaXdsServer> {
        DeltaXdsServer::with_static_token("test-token").expect("build test xDS server")
    }

    fn test_node() -> NodeId {
        NodeId::new("test-node").expect("valid test node")
    }

    fn xds_resource(resource_type: ResourceType, name: String, payload: Any) -> XdsResource {
        let payload = prost_types::Any {
            type_url: payload.type_url,
            value: payload.value,
        };
        match sandbox_id_from_resource_name(&name) {
            Some(sandbox_id) => XdsResource::new(sandbox_id, resource_type, name, payload),
            None => XdsResource::shared(resource_type, name, payload),
        }
    }

    fn authenticated_stream_request(
        stream: ReceiverStream<DeltaDiscoveryRequest>,
    ) -> Request<ReceiverStream<DeltaDiscoveryRequest>> {
        let mut request = Request::new(stream);
        request
            .metadata_mut()
            .insert("authorization", "Bearer test-token".parse().unwrap());
        request
            .metadata_mut()
            .insert("x-joysafeter-node-id", "test-node".parse().unwrap());
        request
    }

    #[tokio::test]
    async fn standby_rejects_new_ads_and_revocation_closes_existing_streams() {
        let server = test_server();
        server.set_serving(false);

        let listener = TcpListener::bind("127.0.0.1:0")
            .await
            .expect("bind xDS test listener");
        let address = listener.local_addr().expect("read xDS test address");
        let (shutdown_tx, shutdown_rx) = oneshot::channel();
        let service = server.clone();
        let server_task = tokio::spawn(async move {
            Server::builder()
                .add_service(AggregatedDiscoveryServiceServer::from_arc(service))
                .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                    let _ = shutdown_rx.await;
                })
                .await
        });

        let channel = tonic::transport::Endpoint::from_shared(format!("http://{address}"))
            .expect("build xDS test endpoint")
            .connect()
            .await
            .expect("connect xDS test client");
        let mut client = AggregatedDiscoveryServiceClient::new(channel);
        let (_standby_tx, standby_rx) = tokio::sync::mpsc::channel(1);
        let error = client
            .delta_aggregated_resources(authenticated_stream_request(ReceiverStream::new(
                standby_rx,
            )))
            .await
            .expect_err("standby xDS server must reject new ADS streams");
        assert_eq!(error.code(), tonic::Code::Unavailable);

        server.set_serving(true);
        let (_active_tx, active_rx) = tokio::sync::mpsc::channel(1);
        let mut stream = client
            .delta_aggregated_resources(authenticated_stream_request(ReceiverStream::new(
                active_rx,
            )))
            .await
            .expect("active xDS server must accept ADS streams")
            .into_inner();

        server.set_serving(false);
        let closed = tokio::time::timeout(Duration::from_secs(1), stream.message())
            .await
            .expect("revoked ADS stream must close promptly")
            .expect("revoked ADS stream must close without transport error");
        assert!(closed.is_none());

        let _ = shutdown_tx.send(());
        server_task
            .await
            .expect("join xDS test server")
            .expect("stop xDS test server");
    }

    /// Regression: `DeltaXdsServer::apply` must not self-deadlock when it records
    /// pending sandbox status. It previously called
    /// `status_notify.send(*status_notify.borrow() + 1)`, holding the watch read
    /// guard from `borrow()` across `send()`'s write acquisition on the same
    /// channel — a permanent single-thread read-then-write deadlock that only ran
    /// in gRPC xDS mode (the LDS listener push carries a non-empty
    /// `pending_sandboxes`). It wedged the global `config_apply_lock` and made
    /// every sandbox's networking reconcile time out, so Envoy never received the
    /// per-sandbox listener and `/sockets/<id>/http.sock` was never created.
    #[tokio::test]
    async fn grpc_lds_upsert_with_pending_status_does_not_deadlock() {
        let server = test_server();
        let lds = GrpcLds::new(server.clone());
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = SandboxId::from_uuid(Uuid::from_u128(1));

        // Before the fix this future never resolves; bound it so the test fails
        // as a timeout instead of hanging the whole test binary.
        let result = tokio::time::timeout(
            std::time::Duration::from_secs(5),
            lds.upsert(vec![listener]),
        )
        .await;

        assert!(
            result.is_ok(),
            "GrpcLds::upsert deadlocked while recording pending xDS status"
        );
        result.unwrap().expect("upsert should succeed");

        // The pending status was recorded for the sandbox.
        assert!(matches!(
            server
                .control_plane
                .lock()
                .expect("xDS control-plane lock poisoned")
                .apply_status(SandboxId::from_uuid(Uuid::from_u128(1))),
            Some(ApplyStatus::Pending { .. })
        ));
    }

    #[tokio::test]
    async fn stale_ack_is_ignored_until_current_version_is_acked() {
        let server = test_server();
        let lds = GrpcLds::new(server.clone());
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(2));
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;
        let stream_id = StreamId::new(10);
        let control_plane = server.control_plane_handle();
        control_plane.register_stream(test_node(), stream_id);

        lds.upsert(vec![listener]).await.unwrap();
        let (min_version, placement_revision) = match server
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .apply_status(sandbox)
        {
            Some(ApplyStatus::Pending {
                min_version,
                placement_revision,
                ..
            }) => (min_version, placement_revision),
            other => panic!("expected pending xDS status, got {other:?}"),
        };
        let resource = format!("{}_http", sandbox.as_uuid());
        control_plane.record_response(
            std::slice::from_ref(&resource),
            min_version.saturating_sub(1),
            placement_revision,
            &test_node(),
            stream_id,
            ResourceType::Listener,
            AckDisposition::Ack,
        );
        assert!(matches!(
            server
                .control_plane
                .lock()
                .expect("xDS control-plane lock poisoned")
                .apply_status(sandbox),
            Some(ApplyStatus::Pending { .. })
        ));

        control_plane.record_response(
            &[resource],
            min_version,
            placement_revision,
            &test_node(),
            stream_id,
            ResourceType::Listener,
            AckDisposition::Ack,
        );
        server
            .wait_for_sandbox_ack(sandbox, Duration::from_millis(50))
            .await
            .expect("current xDS version ACK must release waiter");
    }

    #[tokio::test]
    async fn current_nack_is_returned_to_waiter() {
        let server = test_server();
        let lds = GrpcLds::new(server.clone());
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(3));
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;
        let stream_id = StreamId::new(11);
        let control_plane = server.control_plane_handle();
        control_plane.register_stream(test_node(), stream_id);

        lds.upsert(vec![listener]).await.unwrap();
        let (min_version, placement_revision) = match server
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .apply_status(sandbox)
        {
            Some(ApplyStatus::Pending {
                min_version,
                placement_revision,
                ..
            }) => (min_version, placement_revision),
            other => panic!("expected pending xDS status, got {other:?}"),
        };
        control_plane.record_response(
            &[format!("{}_http", sandbox.as_uuid())],
            min_version,
            placement_revision,
            &test_node(),
            stream_id,
            ResourceType::Listener,
            AckDisposition::Nack("invalid listener".to_string()),
        );

        let error = server
            .wait_for_sandbox_ack(sandbox, Duration::from_millis(50))
            .await
            .expect_err("current NACK must reject publication");
        assert!(error.to_string().contains("invalid listener"));
    }

    #[tokio::test]
    async fn pending_xds_generation_times_out_without_ack() {
        let server = test_server();
        let lds = GrpcLds::new(server.clone());
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(4));
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;

        lds.upsert(vec![listener]).await.unwrap();
        let error = server
            .wait_for_sandbox_ack(sandbox, Duration::from_millis(10))
            .await
            .expect_err("missing ACK must time out");
        assert!(error
            .to_string()
            .contains("timed out waiting for Envoy xDS ACK"));
    }

    #[tokio::test]
    async fn update_without_connected_stream_retains_version_for_reconnect_snapshot() {
        let server = test_server();
        let lds = GrpcLds::new(server.clone());
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(5));
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;

        lds.upsert(vec![listener]).await.unwrap();

        let state_version = server
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .version();
        assert_eq!(state_version, 1);
        assert_eq!(
            *server.notify.borrow(),
            state_version,
            "a reconnecting stream must snapshot the latest resource version"
        );
    }

    /// `forget_sandbox` must drop retained ACK/NACK bookkeeping so domain state
    /// stays bounded across a sandbox's lifecycle (create → teardown).
    #[tokio::test]
    async fn forget_sandbox_clears_apply_status() {
        let server = test_server();
        let lds = GrpcLds::new(server.clone());
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(7));
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;

        lds.upsert(vec![listener]).await.unwrap();
        assert!(server
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .apply_status(sandbox)
            .is_some());

        lds.forget_sandbox(sandbox).await;
        assert!(
            server
                .control_plane
                .lock()
                .expect("xDS control-plane lock poisoned")
                .apply_status(sandbox)
                .is_none(),
            "apply state must be cleared on teardown"
        );
    }

    #[tokio::test]
    async fn grpc_lds_reports_configured_sandbox_ids() {
        let server = test_server();
        let lds = GrpcLds::new(server);
        let first = SandboxId::from_uuid(Uuid::from_u128(8));
        let second = SandboxId::from_uuid(Uuid::from_u128(9));
        let mut first_listener = spec(ListenerKind::Http, &["first.example.com"]);
        first_listener.sandbox_id = first;
        let mut second_listener = spec(ListenerKind::Http, &["second.example.com"]);
        second_listener.sandbox_id = second;

        lds.upsert(vec![first_listener, second_listener])
            .await
            .expect("listener upsert");

        assert_eq!(
            lds.configured_sandbox_ids().await,
            std::collections::HashSet::from([first, second])
        );
    }

    /// The nonce tracker is bounded and FIFO-evicts oldest entries, so a stream
    /// that pushes far more updates than Envoy ACKs cannot leak nonce state.
    #[test]
    fn nonce_tracker_is_bounded_and_fifo() {
        let mut tracker = NonceTracker::default();
        for i in 0..(XDS_NONCE_TRACK_LIMIT + 50) {
            tracker.insert(
                format!("n-{i}"),
                NonceContext {
                    resource_type: ResourceType::Listener,
                    resource_version: i as u64,
                    placement_revision: PlacementRevision::new(0),
                    resource_names: vec![],
                },
            );
        }
        assert!(tracker.map.len() <= XDS_NONCE_TRACK_LIMIT);
        assert_eq!(tracker.map.len(), tracker.order.len());
        // Oldest were evicted; a recent one survives and is consumed on take().
        let recent = format!("n-{}", XDS_NONCE_TRACK_LIMIT + 49);
        assert!(tracker.take(&recent).is_some());
        assert!(tracker.take(&recent).is_none(), "take must consume");
        assert!(tracker.take("n-0").is_none(), "oldest was evicted");
    }

    /// `apply_sandbox_batch` applies clusters and listeners under ONE version
    /// tick (single stream wake) with clusters recorded before listeners, and
    /// removes stale clusters under the sandbox's prefix.
    #[tokio::test]
    async fn apply_sandbox_batch_is_atomic_and_ordered() {
        let server = test_server();
        let lds = GrpcLds::new(server.clone());
        let sandbox = SandboxId::from_uuid(Uuid::from_u128(9));
        let prefix = format!("up_{sandbox}_");

        // Seed a stale cluster under the prefix that should be pruned.
        server
            .apply(
                ResourceType::Cluster,
                vec![InventoryMutation::upsert(xds_resource(
                    ResourceType::Cluster,
                    format!("{prefix}stale_443"),
                    encode_cluster_any(&ClusterSpec {
                        name: format!("{prefix}stale_443"),
                        upstream_host: "old.example.com".to_string(),
                        upstream_port: 443,
                        upstream_tls: true,
                        vetted_addresses: vec![],
                    })
                    .unwrap(),
                ))],
                vec![],
            )
            .await;
        let version_before = server
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned")
            .version();

        let clusters = vec![ClusterSpec {
            name: format!("{prefix}new_443"),
            upstream_host: "new.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            vetted_addresses: vec![],
        }];
        let mut listener = spec(ListenerKind::Http, &["example.com"]);
        listener.sandbox_id = sandbox;

        let applied = lds
            .apply_sandbox_batch(clusters, vec![listener], prefix.clone())
            .await
            .unwrap();
        assert!(applied, "grpc backend must apply the batch");

        let control_plane = server
            .control_plane
            .lock()
            .expect("xDS control-plane lock poisoned");
        // Exactly one version tick for the combined CDS+LDS update.
        assert_eq!(control_plane.version(), version_before + 1);
        // Both change-log groups share that single version.
        let batch: Vec<_> = control_plane
            .changes_since(version_before)
            .expect("change log contains latest batch")
            .into_iter()
            .filter(|change| change.version() == control_plane.version())
            .collect();
        assert_eq!(batch.len(), 2, "one CDS group + one LDS group");
        assert_eq!(
            batch[0].resource_type(),
            ResourceType::Cluster,
            "CDS before LDS"
        );
        assert_eq!(batch[1].resource_type(), ResourceType::Listener);
        // Stale cluster pruned, new cluster present, listener present.
        let clusters_now = control_plane.snapshot_type(ResourceType::Cluster);
        assert!(clusters_now.contains_key(&format!("{prefix}new_443")));
        assert!(!clusters_now.contains_key(&format!("{prefix}stale_443")));
        assert!(control_plane
            .snapshot_type(ResourceType::Listener)
            .contains_key(&format!("{}_http", sandbox.as_uuid())));
    }

    fn spec(kind: ListenerKind, hosts: &[&str]) -> ListenerSpec {
        ListenerSpec {
            sandbox_id: SandboxId::from_uuid(Uuid::nil()),
            kind,
            allowed_hosts: hosts.iter().map(|s| s.to_string()).collect(),
            credentials: vec![],
            proxy_auth_token: None,
        }
    }

    fn spec_with_creds(
        kind: ListenerKind,
        hosts: &[&str],
        creds: Vec<EgressCredentialRoute>,
    ) -> ListenerSpec {
        ListenerSpec {
            sandbox_id: SandboxId::from_uuid(Uuid::nil()),
            kind,
            allowed_hosts: hosts.iter().map(|s| s.to_string()).collect(),
            credentials: creds,
            proxy_auth_token: None,
        }
    }

    fn llm_route() -> EgressCredentialRoute {
        EgressCredentialRoute {
            id: "llm".to_string(),
            kind: EgressKind::Llm,
            exposure: EgressExposure::Placeholder,
            match_host: LLM_EGRESS_HOST.to_string(),
            path_mapping: EgressPathMapping::RewritePrefix {
                exposed_prefix: "/".to_string(),
                upstream_prefix: "/v1/".to_string(),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "llm.internal.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
            vetted_addresses: vec![],
            inject_headers: vec![("authorization".to_string(), "Bearer sk-secret".to_string())],
            remove_headers: vec![],
        }
    }

    fn mcp_route(name: &str) -> EgressCredentialRoute {
        EgressCredentialRoute {
            id: format!("mcp:{name}"),
            kind: EgressKind::Mcp,
            exposure: EgressExposure::Placeholder,
            match_host: MCP_EGRESS_HOST.to_string(),
            path_mapping: EgressPathMapping::RewritePrefix {
                exposed_prefix: format!("/mcp/{name}/"),
                upstream_prefix: "/sse".to_string(),
            },
            retry_mode: EgressRetryMode::Disabled,
            upstream_host: "mcp.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
            vetted_addresses: vec![],
            inject_headers: vec![("authorization".to_string(), "Bearer tok".to_string())],
            remove_headers: vec![],
        }
    }

    #[test]
    fn listener_resource_names_use_http_suffix() {
        assert_eq!(
            spec(ListenerKind::Http, &[]).resource_name(),
            "00000000-0000-0000-0000-000000000000_http"
        );
    }

    #[test]
    fn xds_resource_names_map_back_to_sandbox_ids() {
        let id =
            SandboxId::from_uuid(Uuid::parse_str("018f5f50-0000-7000-8000-000000000001").unwrap());
        assert_eq!(
            sandbox_id_from_resource_name(&format!("{}_http", id.as_uuid())),
            Some(id)
        );
        assert_eq!(
            sandbox_id_from_resource_name(&format!("up_{}_external_api", id.as_uuid())),
            Some(id)
        );
        assert_eq!(
            sandbox_id_from_resource_name(&format!("{}_grpc", id.as_uuid())),
            None
        );
        assert_eq!(sandbox_id_from_resource_name("dynamic_forward_proxy"), None);
    }

    #[test]
    fn validates_duplicate_credential_and_allowlist_domains() {
        let sid = SandboxId::from_uuid(Uuid::nil());
        let policy = SandboxEgressPolicy {
            allowlist_hosts: vec![LLM_EGRESS_HOST.to_string()],
            credential_routes: vec![llm_route()],
            proxy_auth_token: None,
        };
        let err = validate_egress_policy(&sid, &policy)
            .unwrap_err()
            .to_string();
        assert!(err.contains("overlaps credential-injection host"), "{err}");
    }

    #[test]
    fn policy_summary_hashes_injected_header_values() {
        let sid = SandboxId::from_uuid(Uuid::nil());
        let policy = SandboxCredentials {
            routes: vec![llm_route()],
            proxy_auth_token: None,
        }
        .to_policy(&sid, vec![]);
        let summary = rendered_egress_policy_summary(&sid, &policy);
        let text = summary.to_string();
        assert!(text.contains("value_sha256"));
        assert!(!text.contains("Bearer sk-secret"));
    }

    #[test]
    fn http_listener_encodes_with_allowlist_and_deny_all() {
        let any = encode_listener_any(&spec(ListenerKind::Http, &["api.example.com"])).unwrap();
        assert_eq!(any.type_url, LISTENER_TYPE_URL);
        use envoy_types::pb::envoy::config::listener::v3::Listener;
        let l = Listener::decode(any.value.as_slice()).unwrap();
        assert_eq!(l.name, "00000000-0000-0000-0000-000000000000_http");
        assert_eq!(l.filter_chains.len(), 1);
    }

    #[test]
    fn json_and_proto_agree_on_listener_name() {
        // The filesystem (JSON) and gRPC (proto) backends must name resources
        // identically so a mode switch is transparent to Envoy.
        let http = spec(ListenerKind::Http, &["a.com"]);
        let json = render_listener_json(&http);
        assert_eq!(json["name"], "00000000-0000-0000-0000-000000000000_http");
        assert_eq!(json["@type"], LISTENER_TYPE_URL);
    }

    #[test]
    fn credentials_produce_matching_routes_and_clusters() {
        // Full-shape check: placeholder-host routes host_rewrite to the real
        // upstream and reference a per-upstream STRICT_DNS cluster that CDS
        // delivers. Validated live against Envoy; this locks the wire shape.
        let creds = SandboxCredentials {
            routes: vec![
                EgressCredentialRoute {
                    id: "llm".to_string(),
                    kind: EgressKind::Llm,
                    exposure: EgressExposure::Placeholder,
                    match_host: LLM_EGRESS_HOST.to_string(),
                    path_mapping: EgressPathMapping::RewritePrefix {
                        exposed_prefix: "/".to_string(),
                        upstream_prefix: "/v1/".to_string(),
                    },
                    retry_mode: EgressRetryMode::SafeIdempotent,
                    upstream_host: "llm.internal.example.com".to_string(),
                    upstream_port: 443,
                    upstream_tls: true,
                    cluster_name: String::new(),
                    vetted_addresses: vec![],
                    inject_headers: vec![("authorization".to_string(), "Bearer sk".to_string())],
                    remove_headers: vec![],
                },
                EgressCredentialRoute {
                    id: "mcp:gitlab".to_string(),
                    kind: EgressKind::Mcp,
                    exposure: EgressExposure::Placeholder,
                    match_host: MCP_EGRESS_HOST.to_string(),
                    path_mapping: EgressPathMapping::RewritePrefix {
                        exposed_prefix: "/mcp/gitlab/".to_string(),
                        upstream_prefix: "/sse".to_string(),
                    },
                    retry_mode: EgressRetryMode::Disabled,
                    upstream_host: "mcp.example.com".to_string(),
                    upstream_port: 8443,
                    upstream_tls: true,
                    cluster_name: String::new(),
                    vetted_addresses: vec![],
                    inject_headers: vec![("authorization".to_string(), "Bearer t".to_string())],
                    remove_headers: vec![],
                },
            ],
            proxy_auth_token: None,
        };
        let sid = SandboxId::from_uuid(Uuid::nil());
        let routes = creds.to_routes(&sid);
        let clusters = creds.to_clusters(&sid);

        // No per-sandbox clusters — routes point to shared DFP clusters.
        assert!(
            clusters.is_empty(),
            "per-sandbox clusters should not be created; routes use shared DFP"
        );

        // Every route's cluster_name must be one of the shared DFP clusters.
        for r in &routes {
            assert!(
                r.cluster_name == "dynamic_forward_proxy_tls"
                    || r.cluster_name == "dynamic_forward_proxy",
                "route cluster {} must be a shared DFP cluster",
                r.cluster_name
            );
        }

        // LLM route: placeholder match host, host_rewrite to real upstream.
        let llm = routes
            .iter()
            .find(|r| r.match_host == LLM_EGRESS_HOST)
            .unwrap();
        assert_eq!(
            llm.path_mapping,
            EgressPathMapping::RewritePrefix {
                exposed_prefix: "/".to_string(),
                upstream_prefix: "/v1/".to_string(),
            }
        );
        assert_eq!(llm.upstream_host, "llm.internal.example.com");
        assert_eq!(llm.cluster_name, "dynamic_forward_proxy_tls");

        // MCP route scoped by name.
        let mcp = routes
            .iter()
            .find(|r| r.match_host == MCP_EGRESS_HOST)
            .unwrap();
        assert_eq!(
            mcp.path_mapping,
            EgressPathMapping::RewritePrefix {
                exposed_prefix: "/mcp/gitlab/".to_string(),
                upstream_prefix: "/sse".to_string(),
            }
        );
        assert_eq!(mcp.retry_mode, EgressRetryMode::Disabled);
        assert_eq!(mcp.cluster_name, "dynamic_forward_proxy_tls");
    }

    #[test]
    fn external_placeholder_and_transparent_routes_share_one_cluster() {
        // An external service emits two routes: a placeholder-host route
        // (external-egress.internal/services/<name>/) and a transparent route on
        // the real host so a skill can call http://crm.example.com/api/ directly.
        // Both now point to the shared dynamic_forward_proxy_tls cluster.
        let sid = SandboxId::from_uuid(Uuid::nil());
        let creds = SandboxCredentials {
            routes: vec![
                EgressCredentialRoute {
                    id: "external:crm".to_string(),
                    kind: EgressKind::External,
                    exposure: EgressExposure::Placeholder,
                    match_host: EXTERNAL_EGRESS_HOST.to_string(),
                    path_mapping: EgressPathMapping::RewritePrefix {
                        exposed_prefix: "/services/crm/".to_string(),
                        upstream_prefix: "/api/".to_string(),
                    },
                    retry_mode: EgressRetryMode::SafeIdempotent,
                    upstream_host: "crm.example.com".to_string(),
                    upstream_port: 443,
                    upstream_tls: true,
                    cluster_name: String::new(),
                    vetted_addresses: vec![],
                    inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
                    remove_headers: vec!["cookie".to_string()],
                },
                EgressCredentialRoute {
                    id: "external-direct:crm".to_string(),
                    kind: EgressKind::External,
                    exposure: EgressExposure::Transparent,
                    match_host: "crm.example.com".to_string(),
                    path_mapping: EgressPathMapping::Passthrough {
                        matcher: EgressPathMatcher::Prefix("/api/".to_string()),
                    },
                    retry_mode: EgressRetryMode::SafeIdempotent,
                    upstream_host: "crm.example.com".to_string(),
                    upstream_port: 443,
                    upstream_tls: true,
                    cluster_name: String::new(),
                    vetted_addresses: vec![],
                    inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
                    remove_headers: vec!["cookie".to_string()],
                },
            ],
            proxy_auth_token: None,
        };

        let routes = creds.to_routes(&sid);
        let clusters = creds.to_clusters(&sid);

        // No per-sandbox clusters; both routes use shared DFP.
        assert_eq!(routes.len(), 2);
        assert!(clusters.is_empty());
        assert_eq!(routes[0].cluster_name, "dynamic_forward_proxy_tls");
        assert_eq!(routes[1].cluster_name, "dynamic_forward_proxy_tls");

        // Transparent route matches the real host and rewrites are no-ops.
        let direct = routes
            .iter()
            .find(|r| r.match_host == "crm.example.com")
            .unwrap();
        assert_eq!(direct.exposure, EgressExposure::Transparent);
        assert_eq!(
            direct.path_mapping,
            EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix("/api/".to_string())
            }
        );
        assert_eq!(direct.upstream_host, "crm.example.com");
        assert!(direct.upstream_tls);
        assert_eq!(direct.cluster_name, "dynamic_forward_proxy_tls");

        // The transparent host gets its own credential vhost keyed on the real
        // host. In production the real host is NOT added to allowed_hosts (see
        // merge_egress_hosts), so no vhost collides on that exact domain. Build
        // the listener the way it is actually assembled — transparent routes +
        // an allowlist that does NOT contain the transparent host — and assert
        // every exact domain is unique across vhosts (Envoy rejects duplicates).
        let vh = build_virtual_hosts_json(&["other.example.com".to_string()], &routes, None);
        assert!(vh.iter().any(|v| v["name"] == "egress_crm_example_com"));

        let mut seen = std::collections::HashSet::new();
        for v in &vh {
            for d in v["domains"].as_array().unwrap() {
                let domain = d.as_str().unwrap().to_string();
                if domain == "*" {
                    continue;
                }
                assert!(
                    seen.insert(domain.clone()),
                    "duplicate exact domain across vhosts: {domain}"
                );
            }
        }
    }

    #[test]
    fn pinned_mcp_addresses_produce_static_cluster_with_original_sni() {
        let sid = SandboxId::from_uuid(Uuid::nil());
        let mut route = mcp_route("pinned");
        route.cluster_name.clear();
        route.vetted_addresses = vec!["203.0.113.10".to_string(), "2001:db8::10".to_string()];
        let credentials = SandboxCredentials {
            routes: vec![route],
            proxy_auth_token: None,
        };

        let routes = credentials.to_routes(&sid);
        let clusters = credentials.to_clusters(&sid);
        let policy = credentials.to_policy(&sid, vec![]);

        assert_eq!(clusters.len(), 1);
        validate_egress_policy(&sid, &policy).unwrap();
        assert_eq!(routes[0].cluster_name, clusters[0].name);
        assert_eq!(clusters[0].upstream_host, "mcp.example.com");
        assert_eq!(
            clusters[0].vetted_addresses,
            vec!["203.0.113.10".to_string(), "2001:db8::10".to_string()]
        );

        let json = render_cluster_json(&clusters[0]);
        assert_eq!(json["type"], "STATIC");
        assert_eq!(
            json["transport_socket"]["typed_config"]["sni"],
            "mcp.example.com"
        );
        let endpoints = json["load_assignment"]["endpoints"][0]["lb_endpoints"]
            .as_array()
            .unwrap();
        assert_eq!(endpoints.len(), 2);
        assert_eq!(
            endpoints[0]["endpoint"]["address"]["socket_address"]["address"],
            "203.0.113.10"
        );
        assert_eq!(
            endpoints[1]["endpoint"]["address"]["socket_address"]["address"],
            "2001:db8::10"
        );

        use envoy_types::pb::envoy::config::cluster::v3::{cluster, Cluster};
        let encoded = encode_cluster_any(&clusters[0]).unwrap();
        let decoded = Cluster::decode(encoded.value.as_slice()).unwrap();
        assert_eq!(
            decoded.cluster_discovery_type,
            Some(cluster::ClusterDiscoveryType::Type(
                cluster::DiscoveryType::Static as i32
            ))
        );
        let proto_endpoints = &decoded.load_assignment.unwrap().endpoints[0].lb_endpoints;
        assert_eq!(proto_endpoints.len(), 2);
    }

    #[test]
    fn same_host_multiple_base_paths_share_one_vhost() {
        // Two external services on the same host but different base paths
        // (e.g. crm.example.com/api/ and crm.example.com/auth/). Their
        // transparent routes must land in ONE vhost for that host, ordered
        // longest-prefix-first, with the host's exact domain declared once.
        let sid = SandboxId::from_uuid(Uuid::nil());
        let mk = |id: &str, prefix: &str| EgressCredentialRoute {
            id: id.to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "crm.example.com".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix(prefix.to_string()),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "crm.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: String::new(),
            vetted_addresses: vec![],
            inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
            remove_headers: vec!["cookie".to_string()],
        };
        let creds = SandboxCredentials {
            routes: vec![
                mk("external-direct:crm-api", "/api/"),
                mk("external-direct:crm-auth", "/auth/api/"),
            ],
            proxy_auth_token: None,
        };
        let routes = creds.to_routes(&sid);
        let vh = build_virtual_hosts_json(&[], &routes, None);

        // Exactly one credential vhost for the host, holding both routes.
        let host_vhosts: Vec<_> = vh
            .iter()
            .filter(|v| v["name"] == "egress_crm_example_com")
            .collect();
        assert_eq!(host_vhosts.len(), 1);
        let vhost_routes = host_vhosts[0]["routes"].as_array().unwrap();
        assert_eq!(vhost_routes.len(), 2);
        // Longest prefix first: /auth/api/ (10) before /api/ (5).
        assert_eq!(vhost_routes[0]["match"]["prefix"], "/auth/api/");
        assert_eq!(vhost_routes[1]["match"]["prefix"], "/api/");

        // Exact domain declared once across all vhosts.
        let mut seen = std::collections::HashSet::new();
        for v in &vh {
            for d in v["domains"].as_array().unwrap() {
                let domain = d.as_str().unwrap().to_string();
                if domain == "*" {
                    continue;
                }
                assert!(
                    seen.insert(domain.clone()),
                    "duplicate exact domain: {domain}"
                );
            }
        }
    }

    #[test]
    fn passthrough_routes_render_exact_or_prefix_without_rewrite() {
        let exact = EgressCredentialRoute {
            id: "external-direct:crm:0".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "crm.example.com".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Exact("/api/warning/getWarningDetailById".to_string()),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "crm.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
            vetted_addresses: vec![],
            inject_headers: vec![("cookie".to_string(), "SESSION=abc".to_string())],
            remove_headers: vec!["cookie".to_string()],
        };
        let prefix = EgressCredentialRoute {
            id: "external-direct:crm:1".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix("/api/work/".to_string()),
            },
            ..exact.clone()
        };

        let vh = build_virtual_hosts_json(&[], &[exact, prefix], None);
        let routes = vh
            .iter()
            .find(|v| v["name"] == "egress_crm_example_com")
            .unwrap()["routes"]
            .as_array()
            .unwrap();

        let exact_route = routes
            .iter()
            .find(|r| r["match"].get("path").is_some())
            .unwrap();
        assert_eq!(
            exact_route["match"]["path"],
            "/api/warning/getWarningDetailById"
        );
        // Exact routes must not carry a prefix_rewrite.
        assert!(exact_route["route"].get("prefix_rewrite").is_none());

        let prefix_route = routes
            .iter()
            .find(|r| r["match"].get("prefix").is_some())
            .unwrap();
        assert_eq!(prefix_route["match"]["prefix"], "/api/work/");
        // Transparent routes don't need prefix_rewrite (path is already correct).
        assert!(prefix_route["route"].get("prefix_rewrite").is_none());
    }

    #[test]
    fn exact_rewrite_route_has_renderer_parity_and_can_disable_retries() {
        use envoy_types::pb::envoy::config::route::v3::{route, route_match};

        let credential = EgressCredentialRoute {
            id: "mcp:exact".to_string(),
            kind: EgressKind::Mcp,
            exposure: EgressExposure::Placeholder,
            match_host: MCP_EGRESS_HOST.to_string(),
            path_mapping: EgressPathMapping::RewriteExact {
                exposed_path: "/r/exact/".to_string(),
                upstream_path: "/mcp".to_string(),
            },
            retry_mode: EgressRetryMode::Disabled,
            upstream_host: "mcp.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: "mcp_exact".to_string(),
            vetted_addresses: vec![],
            inject_headers: vec![],
            remove_headers: vec![],
        };

        let json_vhosts = build_virtual_hosts_json(&[], &[credential.clone()], None);
        let json_route = &json_vhosts[0]["routes"][0];
        assert_eq!(json_route["match"]["path"], "/r/exact/");
        assert_eq!(json_route["route"]["prefix_rewrite"], "/mcp");
        assert!(json_route["route"].get("retry_policy").is_none());

        let proto_vhosts = build_virtual_hosts_proto(&[], &[credential], None);
        let proto_route = &proto_vhosts[0].routes[0];
        assert!(matches!(
            proto_route.r#match.as_ref().and_then(|value| value.path_specifier.as_ref()),
            Some(route_match::PathSpecifier::Path(path)) if path == "/r/exact/"
        ));
        let action = match proto_route.action.as_ref() {
            Some(route::Action::Route(action)) => action,
            _ => panic!("expected route action"),
        };
        assert_eq!(action.prefix_rewrite, "/mcp");
        assert!(action.retry_policy.is_none());
    }

    #[test]
    fn http_vhosts_have_deny_all_last() {
        // With no allowlist, only the catch-all deny_all vhost exists.
        let vh = build_virtual_hosts_json(&[], &[], None);
        assert_eq!(vh.len(), 1);
        assert_eq!(vh[0]["name"], "deny_all");
        // With an allowlist, `allowed` precedes `deny_all`.
        let vh = build_virtual_hosts_json(&["a.com".to_string()], &[], None);
        assert_eq!(vh.len(), 2);
        assert_eq!(vh[0]["name"], "allowed");
        assert_eq!(vh[1]["name"], "deny_all");
    }

    #[test]
    fn credential_vhosts_precede_allowlist_and_inject_headers() {
        let creds = vec![llm_route(), mcp_route("gitlab"), mcp_route("jira")];
        let vh = build_virtual_hosts_json(&["a.com".to_string()], &creds, None);
        // Placeholder-host vhosts, then allowlist, then deny_all.
        assert_eq!(vh[0]["name"], "egress_llm-egress_internal");
        assert_eq!(vh[1]["name"], "egress_mcp-egress_internal");
        assert_eq!(vh[2]["name"], "allowed");
        assert_eq!(vh[3]["name"], "deny_all");

        // LLM route injects Bearer + rewrites host/prefix to the real upstream,
        // routing to its dedicated cluster.
        let llm_routes = vh[0]["routes"].as_array().unwrap();
        let inj = &llm_routes[0]["request_headers_to_add"][0];
        assert_eq!(inj["header"]["key"], "authorization");
        assert_eq!(inj["header"]["value"], "Bearer sk-secret");
        assert_eq!(inj["append_action"], "OVERWRITE_IF_EXISTS_OR_ADD");
        assert_eq!(
            llm_routes[0]["request_headers_to_remove"]
                .as_array()
                .unwrap(),
            &vec![
                json!("x-api-key"),
                json!("api-key"),
                json!("x-goog-api-key"),
                json!("proxy-authorization")
            ]
        );
        assert_eq!(
            llm_routes[0]["route"]["host_rewrite_literal"],
            "llm.internal.example.com"
        );
        assert_eq!(llm_routes[0]["route"]["prefix_rewrite"], "/v1/");
        assert_eq!(
            llm_routes[0]["route"]["cluster"],
            "dynamic_forward_proxy_tls"
        );

        // MCP vhost: two servers on the placeholder host, each its own prefix.
        let mcp_routes = vh[1]["routes"].as_array().unwrap();
        assert_eq!(mcp_routes.len(), 2);
        assert!(mcp_routes[0]["match"]["prefix"]
            .as_str()
            .unwrap()
            .starts_with("/mcp/"));
        assert_eq!(mcp_routes[0]["route"]["prefix_rewrite"], "/sse");
    }

    #[test]
    fn placeholder_routes_rewrite_the_full_upstream_authority() {
        use envoy_types::pb::envoy::config::route::v3::{route, route_action};

        for (port, tls, expected) in [
            (80, false, "mcp.example.com"),
            (443, true, "mcp.example.com"),
            (8765, false, "mcp.example.com:8765"),
            (8443, true, "mcp.example.com:8443"),
        ] {
            let mut credential = mcp_route("authority");
            credential.upstream_port = port;
            credential.upstream_tls = tls;

            let json_vhosts = build_virtual_hosts_json(&[], &[credential.clone()], None);
            assert_eq!(
                json_vhosts[0]["routes"][0]["route"]["host_rewrite_literal"], expected,
                "JSON authority for port {port}, tls={tls}"
            );

            let proto_vhosts = build_virtual_hosts_proto(&[], &[credential], None);
            let action = match proto_vhosts[0].routes[0].action.as_ref() {
                Some(route::Action::Route(action)) => action,
                _ => panic!("expected route action"),
            };
            assert!(matches!(
                action.host_rewrite_specifier.as_ref(),
                Some(route_action::HostRewriteSpecifier::HostRewriteLiteral(authority))
                    if authority == expected
            ));
        }
    }

    #[test]
    fn proxy_auth_token_is_required_on_egress_routes() {
        let expected = proxy_authorization_value("runner-secret");
        let vh = build_virtual_hosts_json(
            &["a.com".to_string()],
            &[llm_route()],
            Some("runner-secret"),
        );

        let credential_headers = vh[0]["routes"][0]["match"]["headers"].as_array().unwrap();
        assert_eq!(credential_headers[0]["name"], "proxy-authorization");
        assert_eq!(credential_headers[0]["string_match"]["exact"], expected);

        let allowlist_headers = vh[1]["routes"][0]["match"]["headers"].as_array().unwrap();
        assert_eq!(allowlist_headers[0]["name"], "proxy-authorization");
        assert_eq!(allowlist_headers[0]["string_match"]["exact"], expected);
    }

    #[test]
    fn proxy_auth_token_is_required_in_proto_routes() {
        let expected = proxy_authorization_value("runner-secret");
        let mut http = spec_with_creds(ListenerKind::Http, &["a.com"], vec![llm_route()]);
        http.proxy_auth_token = Some("runner-secret".to_string());

        let any = encode_listener_any(&http).unwrap();
        use envoy_types::pb::envoy::config::listener::v3::Listener;
        use envoy_types::pb::envoy::config::route::v3::header_matcher;
        use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
            http_connection_manager, HttpConnectionManager,
        };
        use envoy_types::pb::envoy::r#type::matcher::v3::string_matcher;
        let l = Listener::decode(any.value.as_slice()).unwrap();
        let hcm_any = match &l.filter_chains[0].filters[0].config_type {
            Some(
                envoy_types::pb::envoy::config::listener::v3::filter::ConfigType::TypedConfig(a),
            ) => a,
            _ => panic!("expected typed config"),
        };
        let hcm = HttpConnectionManager::decode(hcm_any.value.as_slice()).unwrap();
        let rc = match hcm.route_specifier {
            Some(http_connection_manager::RouteSpecifier::RouteConfig(rc)) => rc,
            _ => panic!("expected route config"),
        };
        let credential_header = &rc.virtual_hosts[0].routes[0]
            .r#match
            .as_ref()
            .unwrap()
            .headers[0];
        assert_eq!(credential_header.name, "proxy-authorization");
        assert!(matches!(
            credential_header.header_match_specifier.as_ref(),
            Some(header_matcher::HeaderMatchSpecifier::StringMatch(sm))
                if sm.match_pattern == Some(string_matcher::MatchPattern::Exact(expected.clone()))
        ));

        let allowed_header = &rc.virtual_hosts[1].routes[0]
            .r#match
            .as_ref()
            .unwrap()
            .headers[0];
        assert_eq!(allowed_header.name, "proxy-authorization");
        assert!(matches!(
            allowed_header.header_match_specifier.as_ref(),
            Some(header_matcher::HeaderMatchSpecifier::StringMatch(sm))
                if sm.match_pattern == Some(string_matcher::MatchPattern::Exact(expected.clone()))
        ));
    }

    #[test]
    fn json_and_proto_agree_on_credential_injection() {
        let creds = vec![llm_route(), mcp_route("gitlab")];
        let http = spec_with_creds(ListenerKind::Http, &["a.com"], creds);

        // JSON path: credential vhosts present.
        let json = render_listener_json(&http);
        let vhosts = json["filter_chains"][0]["filters"][0]["typed_config"]["route_config"]
            ["virtual_hosts"]
            .as_array()
            .unwrap();
        let json_names: Vec<&str> = vhosts.iter().map(|v| v["name"].as_str().unwrap()).collect();

        // Proto path: decode and compare vhost names.
        let any = encode_listener_any(&http).unwrap();
        use envoy_types::pb::envoy::config::listener::v3::Listener;
        use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
            http_connection_manager, HttpConnectionManager,
        };
        let l = Listener::decode(any.value.as_slice()).unwrap();
        let hcm_any = match &l.filter_chains[0].filters[0].config_type {
            Some(
                envoy_types::pb::envoy::config::listener::v3::filter::ConfigType::TypedConfig(a),
            ) => a,
            _ => panic!("expected typed config"),
        };
        let hcm = HttpConnectionManager::decode(hcm_any.value.as_slice()).unwrap();
        let rc = match hcm.route_specifier {
            Some(http_connection_manager::RouteSpecifier::RouteConfig(rc)) => rc,
            _ => panic!("expected route config"),
        };
        let proto_names: Vec<String> = rc.virtual_hosts.iter().map(|v| v.name.clone()).collect();

        assert_eq!(
            json_names,
            proto_names.iter().map(|s| s.as_str()).collect::<Vec<_>>()
        );
        assert_eq!(json_names[0], "egress_llm-egress_internal");
    }

    #[test]
    fn escape_envoy_header_value_escapes_percent() {
        assert_eq!(escape_envoy_header_value("plain"), "plain");
        assert_eq!(escape_envoy_header_value("a%7Cb"), "a%%7Cb");
        assert_eq!(
            escape_envoy_header_value("sid=x%3Dy%7Cz"),
            "sid=x%%3Dy%%7Cz"
        );
        assert_eq!(escape_envoy_header_value("100%"), "100%%");
        assert_eq!(escape_envoy_header_value("%%already"), "%%%%already");
    }

    #[test]
    fn credential_header_values_with_percent_are_escaped_in_json() {
        let cred = EgressCredentialRoute {
            id: "test".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Transparent,
            match_host: "llm-egress.internal".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Prefix("/v1/".to_string()),
            },
            retry_mode: EgressRetryMode::SafeIdempotent,
            upstream_host: "api.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: "dynamic_forward_proxy_tls".to_string(),
            vetted_addresses: vec![],
            inject_headers: vec![("cookie".to_string(), "session=abc%7Cdef%3Dxyz".to_string())],
            remove_headers: vec![],
        };
        let vh = build_virtual_hosts_json(&[], &[cred], None);
        let header_val = vh[0]["routes"][0]["request_headers_to_add"][0]["header"]["value"]
            .as_str()
            .unwrap();
        // % must be doubled so Envoy treats them as literal
        assert_eq!(header_val, "session=abc%%7Cdef%%3Dxyz");
    }
}
