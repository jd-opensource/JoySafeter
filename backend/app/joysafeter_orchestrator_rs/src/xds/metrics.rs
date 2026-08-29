//! Bounded-cardinality observability for the in-process xDS control plane.

use std::fmt::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use super::authority::{AuthorityMetricsSnapshot, AuthorityPhase};
use super::delivery::DeliveryMetricsSnapshot;
use super::model::ResourceType;

const AUTHORITY_PHASES: [(&str, fn(AuthorityPhase) -> bool); 5] = [
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
    degraded_inventory: AtomicU64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum XdsStreamRejection {
    Unauthenticated,
    AuthorityUnavailable,
    InvalidNodeIdentity,
}

impl XdsMetrics {
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

    pub(crate) fn set_degraded_inventory(&self, count: usize) {
        self.inner
            .degraded_inventory
            .store(count as u64, Ordering::Relaxed);
    }

    pub(crate) fn snapshot(
        &self,
        authority: AuthorityMetricsSnapshot,
        delivery: DeliveryMetricsSnapshot,
    ) -> XdsMetricsSnapshot {
        XdsMetricsSnapshot {
            authority,
            delivery,
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
            degraded_inventory: self.inner.degraded_inventory.load(Ordering::Relaxed),
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
    degraded_inventory: u64,
}

impl XdsMetricsSnapshot {
    pub fn pending_delivery_count(&self) -> usize {
        self.delivery.pending_delivery_count
    }

    pub fn oldest_pending_delivery_age(&self) -> Duration {
        self.delivery.oldest_pending_delivery_age
    }

    pub fn active_envoy_node_count(&self) -> usize {
        self.delivery.active_envoy_node_count
    }

    pub fn ack_total(&self, resource_type: ResourceType) -> u64 {
        match resource_type {
            ResourceType::Cluster => self.cluster_acks,
            ResourceType::Listener => self.listener_acks,
        }
    }

    pub fn nack_total(&self, resource_type: ResourceType) -> u64 {
        match resource_type {
            ResourceType::Cluster => self.cluster_nacks,
            ResourceType::Listener => self.listener_nacks,
        }
    }

    pub fn ownership_transition_total(&self) -> u64 {
        self.ownership_assigned + self.ownership_moved + self.ownership_removed
    }

    pub fn authenticated_stream_total(&self) -> u64 {
        self.authenticated_streams
    }

    pub fn rejected_stream_total(&self) -> u64 {
        self.rejected_unauthenticated_streams
            + self.rejected_authority_unavailable_streams
            + self.rejected_invalid_node_identity_streams
    }

    pub fn reconnect_removal_total(&self) -> u64 {
        self.reconnect_removals
    }

    pub fn degraded_inventory_count(&self) -> u64 {
        self.degraded_inventory
    }

    pub fn render_prometheus(&self) -> String {
        let mut output = String::with_capacity(4096);
        write_metric_header(
            &mut output,
            "joysafeter_xds_enabled",
            "Whether the xDS control plane is enabled.",
            "gauge",
        );
        let _ = writeln!(output, "joysafeter_xds_enabled 1");
        write_metric_header(
            &mut output,
            "joysafeter_xds_authority_phase",
            "Current xDS authority phase as a one-hot gauge.",
            "gauge",
        );
        for (name, matches_phase) in AUTHORITY_PHASES {
            let value = u8::from(matches_phase(self.authority.phase));
            let _ = writeln!(
                output,
                "joysafeter_xds_authority_phase{{phase=\"{name}\"}} {value}"
            );
        }

        write_metric_header(
            &mut output,
            "joysafeter_xds_authority_epoch",
            "Current xDS authority epoch, or zero while standby.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_authority_epoch {}",
            self.authority.phase.epoch().unwrap_or(0)
        );

        write_metric_header(
            &mut output,
            "joysafeter_xds_authority_recovery_duration_seconds",
            "Current or most recently completed xDS authority recovery duration.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_authority_recovery_duration_seconds{{result=\"current\"}} {:.6}",
            self.authority.current_recovery_duration.as_secs_f64()
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_authority_recovery_duration_seconds{{result=\"ready\"}} {:.6}",
            self.authority.last_ready_recovery_duration.as_secs_f64()
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_authority_recovery_duration_seconds{{result=\"revoked\"}} {:.6}",
            self.authority.last_revoked_recovery_duration.as_secs_f64()
        );

        write_metric_header(
            &mut output,
            "joysafeter_xds_authority_recovery_total",
            "Completed xDS authority recoveries by result.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_authority_recovery_total{{result=\"ready\"}} {}",
            self.authority.ready_recovery_total
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_authority_recovery_total{{result=\"revoked\"}} {}",
            self.authority.revoked_recovery_total
        );

        write_metric_header(
            &mut output,
            "joysafeter_xds_authenticated_streams_total",
            "Authenticated ADS streams admitted by the transport.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_authenticated_streams_total {}",
            self.authenticated_streams
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_rejected_streams_total",
            "ADS streams rejected by the transport.",
            "counter",
        );
        for (reason, value) in [
            ("unauthenticated", self.rejected_unauthenticated_streams),
            (
                "authority_unavailable",
                self.rejected_authority_unavailable_streams,
            ),
            (
                "invalid_node_identity",
                self.rejected_invalid_node_identity_streams,
            ),
        ] {
            let _ = writeln!(
                output,
                "joysafeter_xds_rejected_streams_total{{reason=\"{reason}\"}} {value}"
            );
        }

        write_metric_header(
            &mut output,
            "joysafeter_xds_active_envoy_nodes",
            "Envoy node identities with an active ADS session.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_active_envoy_nodes {}",
            self.delivery.active_envoy_node_count
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_pending_deliveries",
            "Published sandbox deliveries awaiting terminal ACK or NACK.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_pending_deliveries {}",
            self.delivery.pending_delivery_count
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_oldest_pending_delivery_age_seconds",
            "Age of the oldest published delivery awaiting a terminal result.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_oldest_pending_delivery_age_seconds {:.6}",
            self.delivery.oldest_pending_delivery_age.as_secs_f64()
        );

        render_resource_counters(
            &mut output,
            "joysafeter_xds_ack_total",
            "Accepted Envoy ACK responses.",
            self.cluster_acks,
            self.listener_acks,
        );
        render_resource_counters(
            &mut output,
            "joysafeter_xds_nack_total",
            "Accepted Envoy NACK responses.",
            self.cluster_nacks,
            self.listener_nacks,
        );

        write_metric_header(
            &mut output,
            "joysafeter_xds_reconnect_upserts_total",
            "Resources retransmitted during ADS initial-version reconciliation.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_reconnect_upserts_total {}",
            self.reconnect_upserts
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_reconnect_removals_total",
            "Stale client resources removed during ADS initial-version reconciliation.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_reconnect_removals_total {}",
            self.reconnect_removals
        );

        write_metric_header(
            &mut output,
            "joysafeter_xds_ownership_transitions_total",
            "Authoritative sandbox node ownership transitions.",
            "counter",
        );
        for (result, value) in [
            ("assigned", self.ownership_assigned),
            ("moved", self.ownership_moved),
            ("removed", self.ownership_removed),
        ] {
            let _ = writeln!(
                output,
                "joysafeter_xds_ownership_transitions_total{{result=\"{result}\"}} {value}"
            );
        }

        write_metric_header(
            &mut output,
            "joysafeter_xds_stale_session_closures_total",
            "ADS sessions superseded by a newer session for the same node.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_stale_session_closures_total {}",
            self.stale_session_closures
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_degraded_inventory",
            "Live limited-networking sandboxes currently persisted as pending, NACKed, or failed.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_degraded_inventory {}",
            self.degraded_inventory
        );
        output
    }
}

fn render_resource_counters(
    output: &mut String,
    name: &str,
    help: &str,
    cluster: u64,
    listener: u64,
) {
    write_metric_header(output, name, help, "counter");
    let _ = writeln!(output, "{name}{{resource_type=\"cluster\"}} {cluster}");
    let _ = writeln!(output, "{name}{{resource_type=\"listener\"}} {listener}");
}

fn write_metric_header(output: &mut String, name: &str, help: &str, metric_type: &str) {
    let _ = writeln!(output, "# HELP {name} {help}");
    let _ = writeln!(output, "# TYPE {name} {metric_type}");
}
