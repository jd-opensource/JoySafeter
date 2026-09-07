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

#[test]
fn policy_delivery_and_ha_metrics_are_exported_with_bounded_labels() {
    let metrics = XdsMetrics::default();
    metrics.record_policy_operation(
        PolicyOperation::Apply,
        PolicyOperationResult::Success,
        Duration::from_millis(125),
    );
    metrics.record_delivery(
        PolicyOperation::Apply,
        DeliveryResult::Ack,
        Duration::from_millis(80),
    );
    metrics.record_leader_promotion();
    metrics.record_kubernetes_operation(KubernetesOperation::RenewLease, KubernetesResult::Error);
    let snapshot = metrics.snapshot(
        XdsAuthority::standalone().metrics_snapshot(),
        DeliveryMetricsSnapshot {
            pending_delivery_count: 0,
            oldest_pending_delivery_age: Duration::ZERO,
        },
        Vec::new(),
    );

    let rendered = snapshot.render_prometheus();
    assert!(rendered.contains(
        "joysafeter_agent_gateway_policy_operations_total{operation=\"apply_policy\",result=\"success\"} 1"
    ));
    assert!(rendered.contains(
        "joysafeter_agent_gateway_policy_operation_duration_seconds_count{operation=\"apply_policy\"} 1"
    ));
    assert!(rendered
        .contains("joysafeter_xds_delivery_total{operation=\"apply_policy\",outcome=\"ack\"} 1"));
    assert!(rendered.contains(
        "joysafeter_xds_delivery_duration_seconds_bucket{operation=\"apply_policy\",outcome=\"ack\",le=\"0.1\"} 1"
    ));
    assert!(rendered
        .contains("joysafeter_agent_gateway_leader_transitions_total{transition=\"promote\"} 1"));
    assert!(rendered.contains(
        "joysafeter_agent_gateway_kubernetes_operations_total{operation=\"renew_lease\",result=\"error\"} 1"
    ));
}
