use std::fmt::Write;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum SetupFailureKind {
    AckTimeout,
    RunnerDisconnected,
    StreamError,
    ProtocolError,
    GenerationMismatch,
    RunnerRejected,
    SendFailed,
    AuditPersistence,
}

#[derive(Clone, Default)]
pub(crate) struct RunnerMetrics {
    inner: Arc<RunnerMetricCounters>,
}

#[derive(Default)]
struct RunnerMetricCounters {
    setup_sent: AtomicU64,
    setup_applied: AtomicU64,
    setup_failed: [AtomicU64; 8],
    setup_stale: AtomicU64,
    reconnect_setup_accepted: AtomicU64,
    reconnect_setup_rejected: AtomicU64,
    start_task_dispatched: AtomicU64,
}

impl SetupFailureKind {
    const ALL: [(Self, &'static str); 8] = [
        (Self::AckTimeout, "ack_timeout"),
        (Self::RunnerDisconnected, "runner_disconnected"),
        (Self::StreamError, "stream_error"),
        (Self::ProtocolError, "protocol_error"),
        (Self::GenerationMismatch, "generation_mismatch"),
        (Self::RunnerRejected, "runner_rejected"),
        (Self::SendFailed, "send_failed"),
        (Self::AuditPersistence, "audit_persistence"),
    ];

    fn index(self) -> usize {
        match self {
            Self::AckTimeout => 0,
            Self::RunnerDisconnected => 1,
            Self::StreamError => 2,
            Self::ProtocolError => 3,
            Self::GenerationMismatch => 4,
            Self::RunnerRejected => 5,
            Self::SendFailed => 6,
            Self::AuditPersistence => 7,
        }
    }

    pub(crate) fn as_str(self) -> &'static str {
        Self::ALL[self.index()].1
    }
}

impl RunnerMetrics {
    pub(crate) fn record_setup_sent(&self) {
        self.inner.setup_sent.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_setup_applied(&self) {
        self.inner.setup_applied.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_setup_failed(&self, kind: SetupFailureKind) {
        self.inner.setup_failed[kind.index()].fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_setup_stale(&self) {
        self.inner.setup_stale.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_reconnect_setup(&self, accepted: bool) {
        let counter = if accepted {
            &self.inner.reconnect_setup_accepted
        } else {
            &self.inner.reconnect_setup_rejected
        };
        counter.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_start_task_dispatched(&self) {
        self.inner
            .start_task_dispatched
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn snapshot(&self) -> RunnerMetricsSnapshot {
        RunnerMetricsSnapshot {
            setup_sent: self.inner.setup_sent.load(Ordering::Relaxed),
            setup_applied: self.inner.setup_applied.load(Ordering::Relaxed),
            setup_failed: SetupFailureKind::ALL.map(|(kind, label)| {
                (
                    label,
                    self.inner.setup_failed[kind.index()].load(Ordering::Relaxed),
                )
            }),
            setup_stale: self.inner.setup_stale.load(Ordering::Relaxed),
            reconnect_setup_accepted: self.inner.reconnect_setup_accepted.load(Ordering::Relaxed),
            reconnect_setup_rejected: self.inner.reconnect_setup_rejected.load(Ordering::Relaxed),
            start_task_dispatched: self.inner.start_task_dispatched.load(Ordering::Relaxed),
        }
    }
}

pub(crate) struct RunnerMetricsSnapshot {
    setup_sent: u64,
    setup_applied: u64,
    setup_failed: [(&'static str, u64); 8],
    setup_stale: u64,
    reconnect_setup_accepted: u64,
    reconnect_setup_rejected: u64,
    start_task_dispatched: u64,
}

impl RunnerMetricsSnapshot {
    pub(crate) fn render_prometheus(&self) -> String {
        let mut output = String::with_capacity(2048);
        write_header(
            &mut output,
            "joysafeter_runner_setup_sent_total",
            "SetupSandbox messages sent to authenticated runners.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_runner_setup_sent_total {}",
            self.setup_sent
        );
        write_header(
            &mut output,
            "joysafeter_runner_setup_results_total",
            "Terminal SetupSandbox results accepted by the orchestrator.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_runner_setup_results_total{{result=\"applied\"}} {}",
            self.setup_applied
        );
        write_header(
            &mut output,
            "joysafeter_runner_setup_failures_total",
            "SetupSandbox failures grouped by bounded lifecycle reason.",
            "counter",
        );
        for (reason, value) in self.setup_failed {
            let _ = writeln!(
                output,
                "joysafeter_runner_setup_failures_total{{reason=\"{reason}\"}} {value}"
            );
        }
        write_header(
            &mut output,
            "joysafeter_runner_setup_stale_results_total",
            "SetupSandbox results ignored because setup id or generation was stale.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_runner_setup_stale_results_total {}",
            self.setup_stale
        );
        write_header(
            &mut output,
            "joysafeter_runner_reconnect_setup_total",
            "Runner reconnect setup-generation proofs.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_runner_reconnect_setup_total{{result=\"accepted\"}} {}",
            self.reconnect_setup_accepted
        );
        let _ = writeln!(
            output,
            "joysafeter_runner_reconnect_setup_total{{result=\"rejected\"}} {}",
            self.reconnect_setup_rejected
        );
        write_header(
            &mut output,
            "joysafeter_runner_start_task_dispatched_total",
            "StartTask messages dispatched after a matching SetupSandbox ACK.",
            "counter",
        );
        let _ = writeln!(
            output,
            "joysafeter_runner_start_task_dispatched_total {}",
            self.start_task_dispatched
        );
        output
    }
}

fn write_header(output: &mut String, name: &str, help: &str, metric_type: &str) {
    let _ = writeln!(output, "# HELP {name} {help}");
    let _ = writeln!(output, "# TYPE {name} {metric_type}");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn runner_metrics_render_bounded_lifecycle_labels() {
        let metrics = RunnerMetrics::default();
        metrics.record_setup_sent();
        metrics.record_setup_applied();
        metrics.record_setup_failed(SetupFailureKind::AckTimeout);
        metrics.record_setup_stale();
        metrics.record_reconnect_setup(true);
        metrics.record_reconnect_setup(false);
        metrics.record_start_task_dispatched();

        let rendered = metrics.snapshot().render_prometheus();
        assert!(rendered.contains("joysafeter_runner_setup_sent_total 1"));
        assert!(rendered.contains("joysafeter_runner_setup_results_total{result=\"applied\"} 1"));
        assert!(
            rendered.contains("joysafeter_runner_setup_failures_total{reason=\"ack_timeout\"} 1")
        );
        assert!(rendered.contains("joysafeter_runner_setup_stale_results_total 1"));
        assert!(rendered.contains("joysafeter_runner_reconnect_setup_total{result=\"accepted\"} 1"));
        assert!(rendered.contains("joysafeter_runner_reconnect_setup_total{result=\"rejected\"} 1"));
        assert!(rendered.contains("joysafeter_runner_start_task_dispatched_total 1"));
        assert!(!rendered.contains("sandbox_id"));
        assert!(!rendered.contains("task_id"));
    }
}
