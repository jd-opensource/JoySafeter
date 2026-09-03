use super::*;
use crate::xds::authority::XdsAuthority;
use std::time::Duration;

#[test]
fn stream_lifecycle_and_full_reconciliation_counters_are_exported() {
    let metrics = XdsMetrics::default();
    metrics.record_full_reconciliation();
    metrics.record_node_stream_connection();
    metrics.record_node_stream_disconnect();
    metrics.record_node_ready_transition();
    let snapshot = metrics.snapshot(
        XdsAuthority::standalone().metrics_snapshot(),
        DeliveryMetricsSnapshot {
            pending_delivery_count: 0,
            oldest_pending_delivery_age: Duration::ZERO,
        },
        Vec::new(),
    );

    let rendered = snapshot.render_prometheus();
    assert!(rendered.contains("joysafeter_xds_full_reconciliations_total 1"));
    assert!(rendered.contains("joysafeter_xds_node_stream_connections_total 1"));
    assert!(rendered.contains("joysafeter_xds_node_stream_disconnects_total 1"));
    assert!(rendered.contains("joysafeter_xds_node_ready_transitions_total 1"));
}
