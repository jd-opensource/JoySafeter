use std::fmt::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, RwLock};

use serde::Serialize;

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct XdsRuntimeSnapshot {
    pub connected_streams: usize,
    pub connected_nodes: usize,
    pub source_groups: usize,
    pub node_groups: usize,
    pub snapshot_groups: usize,
    pub candidate_groups: usize,
    pub last_good_groups: usize,
    pub failed_versions: usize,
    pub highest_generation: i64,
    pub revision: u64,
}

#[derive(Default)]
struct XdsRuntimeCounters {
    ack: AtomicU64,
    nack: AtomicU64,
    installed: AtomicU64,
    restored: AtomicU64,
    accepted: AtomicU64,
    rolled_back: AtomicU64,
    timed_out: AtomicU64,
    reconcile_changed: AtomicU64,
    reconcile_unchanged: AtomicU64,
    reconcile_failed: AtomicU64,
}

#[derive(Default)]
struct XdsRuntimeInner {
    snapshot: RwLock<XdsRuntimeSnapshot>,
    counters: XdsRuntimeCounters,
}

#[derive(Clone, Default)]
pub struct XdsRuntimeStatus {
    inner: Arc<XdsRuntimeInner>,
}

impl XdsRuntimeStatus {
    pub fn replace(&self, snapshot: XdsRuntimeSnapshot) {
        *self
            .inner
            .snapshot
            .write()
            .expect("xDS status lock poisoned") = snapshot;
    }

    pub fn snapshot(&self) -> XdsRuntimeSnapshot {
        self.inner
            .snapshot
            .read()
            .expect("xDS status lock poisoned")
            .clone()
    }

    pub fn record_ack(&self) {
        self.inner.counters.ack.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_nack(&self) {
        self.inner.counters.nack.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_installed(&self) {
        self.inner
            .counters
            .installed
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_restored(&self) {
        self.inner.counters.restored.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_accepted(&self) {
        self.inner.counters.accepted.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_rolled_back(&self) {
        self.inner
            .counters
            .rolled_back
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_timed_out(&self) {
        self.inner
            .counters
            .timed_out
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_reconcile_changed(&self) {
        self.inner
            .counters
            .reconcile_changed
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_reconcile_unchanged(&self) {
        self.inner
            .counters
            .reconcile_unchanged
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_reconcile_failed(&self) {
        self.inner
            .counters
            .reconcile_failed
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn render_prometheus(&self, active: bool) -> String {
        let snapshot = self.snapshot();
        let counters = &self.inner.counters;
        let mut output = String::with_capacity(2_048);
        write_gauge(
            &mut output,
            "joysafeter_control_plane_active",
            "Whether this orchestrator holds active control-plane leadership.",
            u8::from(active),
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_connected_streams",
            "Current Rust ADS streams.",
            snapshot.connected_streams,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_connected_nodes",
            "Unique Envoy node identities connected to Rust ADS.",
            snapshot.connected_nodes,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_source_groups",
            "Source policy groups represented by connected Rust ADS streams.",
            snapshot.source_groups,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_node_groups",
            "Node-local xDS groups represented by connected streams.",
            snapshot.node_groups,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_candidate_groups",
            "Node groups with an unaccepted candidate snapshot.",
            snapshot.candidate_groups,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_last_good_groups",
            "Node groups with an accepted last-known-good snapshot.",
            snapshot.last_good_groups,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_failed_versions",
            "Snapshot versions quarantined by Rust ADS.",
            snapshot.failed_versions,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_highest_generation",
            "Highest generation currently served by any Rust ADS node group.",
            snapshot.highest_generation,
        );
        write_gauge(
            &mut output,
            "joysafeter_rust_xds_state_revision",
            "Monotonic in-process Rust ADS state revision.",
            snapshot.revision,
        );
        write_counter_family(
            &mut output,
            "joysafeter_rust_xds_ack_total",
            "Rust ADS ACK and NACK observations.",
            &[
                ("ack", counters.ack.load(Ordering::Relaxed)),
                ("nack", counters.nack.load(Ordering::Relaxed)),
            ],
        );
        write_counter_family(
            &mut output,
            "joysafeter_rust_xds_snapshot_events_total",
            "Rust ADS snapshot lifecycle events.",
            &[
                ("installed", counters.installed.load(Ordering::Relaxed)),
                ("restored", counters.restored.load(Ordering::Relaxed)),
                ("accepted", counters.accepted.load(Ordering::Relaxed)),
                ("rolled_back", counters.rolled_back.load(Ordering::Relaxed)),
                ("timed_out", counters.timed_out.load(Ordering::Relaxed)),
            ],
        );
        write_counter_family(
            &mut output,
            "joysafeter_rust_xds_reconcile_total",
            "PostgreSQL-backed Rust xDS reconciliation outcomes.",
            &[
                (
                    "changed",
                    counters.reconcile_changed.load(Ordering::Relaxed),
                ),
                (
                    "unchanged",
                    counters.reconcile_unchanged.load(Ordering::Relaxed),
                ),
                ("failed", counters.reconcile_failed.load(Ordering::Relaxed)),
            ],
        );
        output
    }
}

fn write_gauge(output: &mut String, name: &str, help: &str, value: impl std::fmt::Display) {
    let _ = writeln!(output, "# HELP {name} {help}");
    let _ = writeln!(output, "# TYPE {name} gauge");
    let _ = writeln!(output, "{name} {value}");
}

fn write_counter_family(output: &mut String, name: &str, help: &str, values: &[(&str, u64)]) {
    let _ = writeln!(output, "# HELP {name} {help}");
    let _ = writeln!(output, "# TYPE {name} counter");
    for (result, value) in values {
        let _ = writeln!(output, "{name}{{result=\"{result}\"}} {value}");
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runtime_status_is_shared_and_replaceable() {
        let status = XdsRuntimeStatus::default();
        let clone = status.clone();
        status.replace(XdsRuntimeSnapshot {
            connected_nodes: 2,
            highest_generation: 42,
            ..XdsRuntimeSnapshot::default()
        });

        assert_eq!(clone.snapshot().connected_nodes, 2);
        assert_eq!(clone.snapshot().highest_generation, 42);
    }

    #[test]
    fn prometheus_output_contains_gauges_and_counters() {
        let status = XdsRuntimeStatus::default();
        status.replace(XdsRuntimeSnapshot {
            connected_streams: 3,
            candidate_groups: 1,
            ..XdsRuntimeSnapshot::default()
        });
        status.record_ack();
        status.record_nack();
        status.record_accepted();
        status.record_reconcile_changed();

        let output = status.render_prometheus(true);
        assert!(output.contains("joysafeter_control_plane_active 1"));
        assert!(output.contains("joysafeter_rust_xds_connected_streams 3"));
        assert!(output.contains("joysafeter_rust_xds_ack_total{result=\"ack\"} 1"));
        assert!(output.contains("joysafeter_rust_xds_snapshot_events_total{result=\"accepted\"} 1"));
        assert!(output.contains("joysafeter_rust_xds_reconcile_total{result=\"changed\"} 1"));
    }
}
