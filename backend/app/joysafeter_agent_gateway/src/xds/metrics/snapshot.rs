use std::fmt::Write;
use std::time::Duration;

use super::{
    DeliveryResult, DurationHistogramSnapshot, KubernetesOperation, KubernetesResult,
    PolicyOperation, PolicyOperationResult, XdsMetricsSnapshot, AUTHORITY_PHASES,
    DURATION_BUCKETS_SECONDS,
};
use crate::xds::model::ResourceType;

impl XdsMetricsSnapshot {
    pub fn pending_delivery_count(&self) -> usize {
        self.delivery.pending_delivery_count
    }

    pub fn oldest_pending_delivery_age(&self) -> Duration {
        self.delivery.oldest_pending_delivery_age
    }

    pub fn active_envoy_node_count(&self) -> usize {
        self.envoy_nodes
            .iter()
            .filter(|node| node.connected)
            .count()
    }

    pub fn ready_envoy_node_count(&self) -> usize {
        self.envoy_nodes.iter().filter(|node| node.ready).count()
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
            self.active_envoy_node_count()
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_ready_envoy_nodes",
            "Envoy nodes whose current ADS session acknowledged CDS and LDS.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_ready_envoy_nodes {}",
            self.ready_envoy_node_count()
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_known_envoy_nodes",
            "Connected or authoritatively assigned Envoy node identities known to this replica.",
            "gauge",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_known_envoy_nodes {}",
            self.envoy_nodes.len()
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_node_stream_connections_total",
            "ADS streams that supplied a valid Envoy node identity.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_node_stream_connections_total {}",
            self.node_stream_connections
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_node_stream_disconnects_total",
            "Current ADS node sessions that disconnected.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_node_stream_disconnects_total {}",
            self.node_stream_disconnects
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_node_ready_transitions_total",
            "Transitions of a current Envoy ADS session into CDS and LDS readiness.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_node_ready_transitions_total {}",
            self.node_ready_transitions
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
            "joysafeter_xds_full_reconciliations_total",
            "Full ADS reconciliations caused by a stream falling behind the bounded revision log.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_xds_full_reconciliations_total {}",
            self.full_reconciliations
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
        write_metric_header(
            &mut output,
            "joysafeter_xds_node_connected",
            "Whether this Gateway replica owns the current ADS stream for an Envoy node.",
            "gauge",
        );
        write_metric_header(
            &mut output,
            "joysafeter_xds_node_ready",
            "Whether the current ADS stream acknowledged CDS and LDS without a newer response pending.",
            "gauge",
        );
        for node in &self.envoy_nodes {
            let node_id = prometheus_label(&node.node_id);
            let _ = writeln!(
                output,
                "joysafeter_xds_node_connected{{node=\"{node_id}\"}} {}",
                u8::from(node.connected)
            );
            let _ = writeln!(
                output,
                "joysafeter_xds_node_ready{{node=\"{node_id}\"}} {}",
                u8::from(node.ready)
            );
        }

        write_metric_header(
            &mut output,
            "joysafeter_agent_gateway_policy_operations_total",
            "Completed policy operations by operation and bounded result class.",
            "counter",
        );
        for operation in PolicyOperation::ALL {
            for result in PolicyOperationResult::ALL {
                let value = self.policy_operations[operation.index()][result.index()];
                let _ = writeln!(
                    output,
                    "joysafeter_agent_gateway_policy_operations_total{{operation=\"{}\",result=\"{}\"}} {value}",
                    operation.label(),
                    result.label()
                );
            }
        }
        write_metric_header(
            &mut output,
            "joysafeter_agent_gateway_policy_operation_duration_seconds",
            "End-to-end policy operation duration, including xDS delivery and replication.",
            "histogram",
        );
        for operation in PolicyOperation::ALL {
            render_duration_histogram(
                &mut output,
                "joysafeter_agent_gateway_policy_operation_duration_seconds",
                &[('o', operation.label())],
                &self.policy_operation_durations[operation.index()],
            );
        }

        write_metric_header(
            &mut output,
            "joysafeter_xds_delivery_total",
            "Terminal exact xDS delivery outcomes by policy operation.",
            "counter",
        );
        for operation in PolicyOperation::ALL {
            for result in DeliveryResult::ALL {
                let value = self.delivery_results[operation.index()][result.index()];
                let _ = writeln!(
                    output,
                    "joysafeter_xds_delivery_total{{operation=\"{}\",outcome=\"{}\"}} {value}",
                    operation.label(),
                    result.label()
                );
            }
        }
        write_metric_header(
            &mut output,
            "joysafeter_xds_delivery_duration_seconds",
            "Time from xDS publication until exact ACK, NACK, or timeout.",
            "histogram",
        );
        for operation in PolicyOperation::ALL {
            for result in DeliveryResult::ALL {
                render_duration_histogram(
                    &mut output,
                    "joysafeter_xds_delivery_duration_seconds",
                    &[('o', operation.label()), ('r', result.label())],
                    &self.delivery_durations[operation.index()][result.index()],
                );
            }
        }

        write_metric_header(
            &mut output,
            "joysafeter_agent_gateway_leader_transitions_total",
            "Successful local Agent Gateway leadership transitions.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_agent_gateway_leader_transitions_total{{transition=\"promote\"}} {}",
            self.leader_promotions
        );
        let _ = writeln!(
            output,
            "joysafeter_agent_gateway_leader_transitions_total{{transition=\"demote\"}} {}",
            self.leader_demotions
        );
        write_metric_header(
            &mut output,
            "joysafeter_agent_gateway_kubernetes_operations_total",
            "Kubernetes Lease and leader-label operation outcomes.",
            "counter",
        );
        for operation in KubernetesOperation::ALL {
            for result in KubernetesResult::ALL {
                let value = self.kubernetes_operations[operation.index()][result.index()];
                let _ = writeln!(
                    output,
                    "joysafeter_agent_gateway_kubernetes_operations_total{{operation=\"{}\",result=\"{}\"}} {value}",
                    operation.label(),
                    result.label()
                );
            }
        }

        for (name, help, value, metric_type) in [
            (
                "joysafeter_agent_gateway_policy_stream_active_connections",
                "Currently active authenticated policy command streams.",
                self.policy_stream_active_connections,
                "gauge",
            ),
            (
                "joysafeter_agent_gateway_policy_stream_connections_total",
                "Authenticated policy command streams accepted by this replica.",
                self.policy_stream_connections,
                "counter",
            ),
            (
                "joysafeter_agent_gateway_policy_stream_commands_in_flight",
                "Policy commands accepted and not yet completed.",
                self.policy_stream_commands_in_flight,
                "gauge",
            ),
            (
                "joysafeter_agent_gateway_policy_stream_queue_saturation_total",
                "Policy commands that encountered a full bounded shard queue.",
                self.policy_stream_queue_saturation,
                "counter",
            ),
        ] {
            write_metric_header(&mut output, name, help, metric_type);
            let _ = writeln!(output, "{name} {value}");
        }
        output
    }
}

fn render_duration_histogram(
    output: &mut String,
    name: &str,
    compact_labels: &[(char, &str)],
    histogram: &DurationHistogramSnapshot,
) {
    let labels = compact_labels
        .iter()
        .map(|(key, value)| match key {
            'o' => format!("operation=\"{value}\""),
            'r' => format!("outcome=\"{value}\""),
            'e' => format!("event_type=\"{value}\""),
            _ => unreachable!("fixed histogram label key"),
        })
        .collect::<Vec<_>>()
        .join(",");
    for (upper_bound, count) in DURATION_BUCKETS_SECONDS.iter().zip(&histogram.buckets) {
        let _ = writeln!(
            output,
            "{name}_bucket{{{labels},le=\"{upper_bound}\"}} {count}"
        );
    }
    let _ = writeln!(
        output,
        "{name}_bucket{{{labels},le=\"+Inf\"}} {}",
        histogram.count
    );
    let _ = writeln!(
        output,
        "{name}_sum{{{labels}}} {:.6}",
        histogram.sum_micros as f64 / 1_000_000.0
    );
    let _ = writeln!(output, "{name}_count{{{labels}}} {}", histogram.count);
}

fn prometheus_label(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('\n', "\\n")
        .replace('"', "\\\"")
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
