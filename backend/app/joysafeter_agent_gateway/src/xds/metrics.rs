//! Bounded-cardinality observability for the in-process xDS control plane.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use super::authority::{AuthorityMetricsSnapshot, AuthorityPhase};
use super::delivery::DeliveryMetricsSnapshot;
use super::model::ResourceType;
use super::node_health::EnvoyNodeStatus;

type AuthorityPhasePredicate = fn(AuthorityPhase) -> bool;

pub(crate) const DURATION_BUCKETS_SECONDS: [f64; 14] = [
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0,
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum PolicyOperation {
    Apply,
    Remove,
}

impl PolicyOperation {
    pub(crate) const ALL: [Self; 2] = [Self::Apply, Self::Remove];

    pub(crate) const fn index(self) -> usize {
        match self {
            Self::Apply => 0,
            Self::Remove => 1,
        }
    }

    pub(crate) const fn label(self) -> &'static str {
        match self {
            Self::Apply => "apply_policy",
            Self::Remove => "remove_policy",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum PolicyOperationResult {
    Success,
    InvalidArgument,
    FailedPrecondition,
    Unavailable,
    DeadlineExceeded,
    Internal,
}

impl PolicyOperationResult {
    pub(crate) const ALL: [Self; 6] = [
        Self::Success,
        Self::InvalidArgument,
        Self::FailedPrecondition,
        Self::Unavailable,
        Self::DeadlineExceeded,
        Self::Internal,
    ];

    pub(crate) const fn index(self) -> usize {
        match self {
            Self::Success => 0,
            Self::InvalidArgument => 1,
            Self::FailedPrecondition => 2,
            Self::Unavailable => 3,
            Self::DeadlineExceeded => 4,
            Self::Internal => 5,
        }
    }

    pub(crate) const fn label(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::InvalidArgument => "invalid_argument",
            Self::FailedPrecondition => "failed_precondition",
            Self::Unavailable => "unavailable",
            Self::DeadlineExceeded => "deadline_exceeded",
            Self::Internal => "internal",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum DeliveryResult {
    Ack,
    Nack,
    Timeout,
}

impl DeliveryResult {
    pub(crate) const ALL: [Self; 3] = [Self::Ack, Self::Nack, Self::Timeout];

    pub(crate) const fn index(self) -> usize {
        match self {
            Self::Ack => 0,
            Self::Nack => 1,
            Self::Timeout => 2,
        }
    }

    pub(crate) const fn label(self) -> &'static str {
        match self {
            Self::Ack => "ack",
            Self::Nack => "nack",
            Self::Timeout => "timeout",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum KubernetesOperation {
    AcquireLease,
    RenewLease,
    ReleaseLease,
    PublishLeaderLabel,
}

impl KubernetesOperation {
    pub(crate) const ALL: [Self; 4] = [
        Self::AcquireLease,
        Self::RenewLease,
        Self::ReleaseLease,
        Self::PublishLeaderLabel,
    ];

    pub(crate) const fn index(self) -> usize {
        match self {
            Self::AcquireLease => 0,
            Self::RenewLease => 1,
            Self::ReleaseLease => 2,
            Self::PublishLeaderLabel => 3,
        }
    }

    pub(crate) const fn label(self) -> &'static str {
        match self {
            Self::AcquireLease => "acquire_lease",
            Self::RenewLease => "renew_lease",
            Self::ReleaseLease => "release_lease",
            Self::PublishLeaderLabel => "publish_leader_label",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum KubernetesResult {
    Success,
    Contended,
    Error,
}

impl KubernetesResult {
    pub(crate) const ALL: [Self; 3] = [Self::Success, Self::Contended, Self::Error];

    pub(crate) const fn index(self) -> usize {
        match self {
            Self::Success => 0,
            Self::Contended => 1,
            Self::Error => 2,
        }
    }

    pub(crate) const fn label(self) -> &'static str {
        match self {
            Self::Success => "success",
            Self::Contended => "contended",
            Self::Error => "error",
        }
    }
}

#[derive(Default)]
struct DurationHistogram {
    buckets: [AtomicU64; DURATION_BUCKETS_SECONDS.len()],
    count: AtomicU64,
    sum_micros: AtomicU64,
}

impl DurationHistogram {
    fn observe(&self, duration: Duration) {
        let seconds = duration.as_secs_f64();
        for (upper_bound, bucket) in DURATION_BUCKETS_SECONDS.iter().zip(&self.buckets) {
            if seconds <= *upper_bound {
                bucket.fetch_add(1, Ordering::Relaxed);
            }
        }
        self.count.fetch_add(1, Ordering::Relaxed);
        self.sum_micros.fetch_add(
            duration.as_micros().min(u64::MAX as u128) as u64,
            Ordering::Relaxed,
        );
    }

    fn snapshot(&self) -> DurationHistogramSnapshot {
        DurationHistogramSnapshot {
            buckets: std::array::from_fn(|index| self.buckets[index].load(Ordering::Relaxed)),
            count: self.count.load(Ordering::Relaxed),
            sum_micros: self.sum_micros.load(Ordering::Relaxed),
        }
    }
}

#[derive(Debug, Clone)]
pub(crate) struct DurationHistogramSnapshot {
    pub(crate) buckets: [u64; DURATION_BUCKETS_SECONDS.len()],
    pub(crate) count: u64,
    pub(crate) sum_micros: u64,
}

const AUTHORITY_PHASES: [(&str, AuthorityPhasePredicate); 5] = [
    ("standby", |phase| matches!(phase, AuthorityPhase::Standby)),
    ("staging", |phase| {
        matches!(phase, AuthorityPhase::Staging { .. })
    }),
    ("recovery_serving", |phase| {
        matches!(phase, AuthorityPhase::RecoveryServing { .. })
    }),
    ("ready", |phase| {
        matches!(phase, AuthorityPhase::Ready { .. })
    }),
    ("revoked", |phase| {
        matches!(phase, AuthorityPhase::Revoked { .. })
    }),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct XdsHealthResponse {
    pub status_code: u16,
    pub body: &'static str,
}

pub fn xds_health(phase: AuthorityPhase) -> XdsHealthResponse {
    match phase {
        AuthorityPhase::Ready { .. } => XdsHealthResponse {
            status_code: 200,
            body: "ready",
        },
        AuthorityPhase::Standby => XdsHealthResponse {
            status_code: 503,
            body: "standby",
        },
        AuthorityPhase::Staging { .. } => XdsHealthResponse {
            status_code: 503,
            body: "staging",
        },
        AuthorityPhase::RecoveryServing { .. } => XdsHealthResponse {
            status_code: 503,
            body: "recovery_serving",
        },
        AuthorityPhase::Revoked { .. } => XdsHealthResponse {
            status_code: 503,
            body: "revoked",
        },
    }
}

#[derive(Clone, Default)]
pub struct XdsMetrics {
    inner: Arc<XdsMetricCounters>,
}

#[derive(Default)]
struct XdsMetricCounters {
    authenticated_streams: AtomicU64,
    rejected_unauthenticated_streams: AtomicU64,
    rejected_authority_unavailable_streams: AtomicU64,
    rejected_invalid_node_identity_streams: AtomicU64,
    cluster_acks: AtomicU64,
    listener_acks: AtomicU64,
    cluster_nacks: AtomicU64,
    listener_nacks: AtomicU64,
    reconnect_upserts: AtomicU64,
    reconnect_removals: AtomicU64,
    ownership_assigned: AtomicU64,
    ownership_moved: AtomicU64,
    ownership_removed: AtomicU64,
    stale_session_closures: AtomicU64,
    full_reconciliations: AtomicU64,
    node_stream_connections: AtomicU64,
    node_stream_disconnects: AtomicU64,
    node_ready_transitions: AtomicU64,
    degraded_inventory: AtomicU64,
    policy_operations: [[AtomicU64; 6]; 2],
    policy_operation_durations: [DurationHistogram; 2],
    delivery_results: [[AtomicU64; 3]; 2],
    delivery_durations: [[DurationHistogram; 3]; 2],
    leader_promotions: AtomicU64,
    leader_demotions: AtomicU64,
    kubernetes_operations: [[AtomicU64; 3]; 4],
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum XdsStreamRejection {
    Unauthenticated,
    AuthorityUnavailable,
    InvalidNodeIdentity,
}

impl XdsMetrics {
    pub(crate) fn record_policy_operation(
        &self,
        operation: PolicyOperation,
        result: PolicyOperationResult,
        duration: Duration,
    ) {
        self.inner.policy_operations[operation.index()][result.index()]
            .fetch_add(1, Ordering::Relaxed);
        self.inner.policy_operation_durations[operation.index()].observe(duration);
    }

    pub(crate) fn record_delivery(
        &self,
        operation: PolicyOperation,
        result: DeliveryResult,
        duration: Duration,
    ) {
        self.inner.delivery_results[operation.index()][result.index()]
            .fetch_add(1, Ordering::Relaxed);
        self.inner.delivery_durations[operation.index()][result.index()].observe(duration);
    }

    pub(crate) fn record_leader_promotion(&self) {
        self.inner.leader_promotions.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_leader_demotion(&self) {
        self.inner.leader_demotions.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_kubernetes_operation(
        &self,
        operation: KubernetesOperation,
        result: KubernetesResult,
    ) {
        self.inner.kubernetes_operations[operation.index()][result.index()]
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_authenticated_stream(&self) {
        self.inner
            .authenticated_streams
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_rejected_stream(&self, reason: XdsStreamRejection) {
        let counter = match reason {
            XdsStreamRejection::Unauthenticated => &self.inner.rejected_unauthenticated_streams,
            XdsStreamRejection::AuthorityUnavailable => {
                &self.inner.rejected_authority_unavailable_streams
            }
            XdsStreamRejection::InvalidNodeIdentity => {
                &self.inner.rejected_invalid_node_identity_streams
            }
        };
        counter.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_ack(&self, resource_type: ResourceType) {
        self.resource_counter(resource_type, false)
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_nack(&self, resource_type: ResourceType) {
        self.resource_counter(resource_type, true)
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_reconnect(&self, upserts: usize, removals: usize) {
        self.inner
            .reconnect_upserts
            .fetch_add(upserts as u64, Ordering::Relaxed);
        self.inner
            .reconnect_removals
            .fetch_add(removals as u64, Ordering::Relaxed);
    }

    pub(crate) fn record_ownership_assigned(&self) {
        self.inner
            .ownership_assigned
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_ownership_moved(&self) {
        self.inner.ownership_moved.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_ownership_removed(&self) {
        self.inner.ownership_removed.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_stale_session_closure(&self) {
        self.inner
            .stale_session_closures
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_full_reconciliation(&self) {
        self.inner
            .full_reconciliations
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_node_stream_connection(&self) {
        self.inner
            .node_stream_connections
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_node_stream_disconnect(&self) {
        self.inner
            .node_stream_disconnects
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_node_ready_transition(&self) {
        self.inner
            .node_ready_transitions
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn set_degraded_inventory(&self, count: usize) {
        self.inner
            .degraded_inventory
            .store(count as u64, Ordering::Relaxed);
    }

    pub(crate) fn snapshot(
        &self,
        authority: AuthorityMetricsSnapshot,
        delivery: DeliveryMetricsSnapshot,
        envoy_nodes: Vec<EnvoyNodeStatus>,
    ) -> XdsMetricsSnapshot {
        XdsMetricsSnapshot {
            authority,
            delivery,
            envoy_nodes,
            authenticated_streams: self.inner.authenticated_streams.load(Ordering::Relaxed),
            rejected_unauthenticated_streams: self
                .inner
                .rejected_unauthenticated_streams
                .load(Ordering::Relaxed),
            rejected_authority_unavailable_streams: self
                .inner
                .rejected_authority_unavailable_streams
                .load(Ordering::Relaxed),
            rejected_invalid_node_identity_streams: self
                .inner
                .rejected_invalid_node_identity_streams
                .load(Ordering::Relaxed),
            cluster_acks: self.inner.cluster_acks.load(Ordering::Relaxed),
            listener_acks: self.inner.listener_acks.load(Ordering::Relaxed),
            cluster_nacks: self.inner.cluster_nacks.load(Ordering::Relaxed),
            listener_nacks: self.inner.listener_nacks.load(Ordering::Relaxed),
            reconnect_upserts: self.inner.reconnect_upserts.load(Ordering::Relaxed),
            reconnect_removals: self.inner.reconnect_removals.load(Ordering::Relaxed),
            ownership_assigned: self.inner.ownership_assigned.load(Ordering::Relaxed),
            ownership_moved: self.inner.ownership_moved.load(Ordering::Relaxed),
            ownership_removed: self.inner.ownership_removed.load(Ordering::Relaxed),
            stale_session_closures: self.inner.stale_session_closures.load(Ordering::Relaxed),
            full_reconciliations: self.inner.full_reconciliations.load(Ordering::Relaxed),
            node_stream_connections: self.inner.node_stream_connections.load(Ordering::Relaxed),
            node_stream_disconnects: self.inner.node_stream_disconnects.load(Ordering::Relaxed),
            node_ready_transitions: self.inner.node_ready_transitions.load(Ordering::Relaxed),
            degraded_inventory: self.inner.degraded_inventory.load(Ordering::Relaxed),
            policy_operations: std::array::from_fn(|operation| {
                std::array::from_fn(|result| {
                    self.inner.policy_operations[operation][result].load(Ordering::Relaxed)
                })
            }),
            policy_operation_durations: std::array::from_fn(|operation| {
                self.inner.policy_operation_durations[operation].snapshot()
            }),
            delivery_results: std::array::from_fn(|operation| {
                std::array::from_fn(|result| {
                    self.inner.delivery_results[operation][result].load(Ordering::Relaxed)
                })
            }),
            delivery_durations: std::array::from_fn(|operation| {
                std::array::from_fn(|result| {
                    self.inner.delivery_durations[operation][result].snapshot()
                })
            }),
            leader_promotions: self.inner.leader_promotions.load(Ordering::Relaxed),
            leader_demotions: self.inner.leader_demotions.load(Ordering::Relaxed),
            kubernetes_operations: std::array::from_fn(|operation| {
                std::array::from_fn(|result| {
                    self.inner.kubernetes_operations[operation][result].load(Ordering::Relaxed)
                })
            }),
        }
    }

    fn resource_counter(&self, resource_type: ResourceType, nack: bool) -> &AtomicU64 {
        match (resource_type, nack) {
            (ResourceType::Cluster, false) => &self.inner.cluster_acks,
            (ResourceType::Listener, false) => &self.inner.listener_acks,
            (ResourceType::Cluster, true) => &self.inner.cluster_nacks,
            (ResourceType::Listener, true) => &self.inner.listener_nacks,
        }
    }
}

#[derive(Debug, Clone)]
pub struct XdsMetricsSnapshot {
    authority: AuthorityMetricsSnapshot,
    delivery: DeliveryMetricsSnapshot,
    envoy_nodes: Vec<EnvoyNodeStatus>,
    authenticated_streams: u64,
    rejected_unauthenticated_streams: u64,
    rejected_authority_unavailable_streams: u64,
    rejected_invalid_node_identity_streams: u64,
    cluster_acks: u64,
    listener_acks: u64,
    cluster_nacks: u64,
    listener_nacks: u64,
    reconnect_upserts: u64,
    reconnect_removals: u64,
    ownership_assigned: u64,
    ownership_moved: u64,
    ownership_removed: u64,
    stale_session_closures: u64,
    full_reconciliations: u64,
    node_stream_connections: u64,
    node_stream_disconnects: u64,
    node_ready_transitions: u64,
    degraded_inventory: u64,
    pub(crate) policy_operations: [[u64; 6]; 2],
    pub(crate) policy_operation_durations: [DurationHistogramSnapshot; 2],
    pub(crate) delivery_results: [[u64; 3]; 2],
    pub(crate) delivery_durations: [[DurationHistogramSnapshot; 3]; 2],
    pub(crate) leader_promotions: u64,
    pub(crate) leader_demotions: u64,
    pub(crate) kubernetes_operations: [[u64; 3]; 4],
}

mod snapshot;

#[cfg(test)]
#[path = "../../tests/unit/xds/metrics_test.rs"]
mod tests;
