use std::sync::atomic::{AtomicU64, Ordering};

static STREAM_CONNECTED: AtomicU64 = AtomicU64::new(0);
static COMMANDS_IN_FLIGHT: AtomicU64 = AtomicU64::new(0);
static CIRCUIT_OPEN: AtomicU64 = AtomicU64::new(0);
static RECONNECTS: AtomicU64 = AtomicU64::new(0);
static CIRCUIT_REJECTIONS: AtomicU64 = AtomicU64::new(0);
static INFLIGHT_REJECTIONS: AtomicU64 = AtomicU64::new(0);
static OVERSIZE_REJECTIONS: AtomicU64 = AtomicU64::new(0);

pub(crate) struct InflightGuard;

impl InflightGuard {
    pub(crate) fn begin() -> Self {
        COMMANDS_IN_FLIGHT.fetch_add(1, Ordering::Relaxed);
        Self
    }
}

impl Drop for InflightGuard {
    fn drop(&mut self) {
        COMMANDS_IN_FLIGHT.fetch_sub(1, Ordering::Relaxed);
    }
}

pub(crate) fn set_stream_connected(connected: bool) {
    STREAM_CONNECTED.store(u64::from(connected), Ordering::Relaxed);
}

pub(crate) fn set_circuit_open(open: bool) {
    CIRCUIT_OPEN.store(u64::from(open), Ordering::Relaxed);
}

pub(crate) fn record_reconnect() {
    RECONNECTS.fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_circuit_rejection() {
    CIRCUIT_REJECTIONS.fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_inflight_rejection() {
    INFLIGHT_REJECTIONS.fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_oversize_rejection() {
    OVERSIZE_REJECTIONS.fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn render_prometheus() -> String {
    format!(
        concat!(
            "# TYPE joysafeter_orchestrator_agent_gateway_policy_stream_connected gauge\n",
            "joysafeter_orchestrator_agent_gateway_policy_stream_connected {}\n",
            "# TYPE joysafeter_orchestrator_agent_gateway_commands_in_flight gauge\n",
            "joysafeter_orchestrator_agent_gateway_commands_in_flight {}\n",
            "# TYPE joysafeter_orchestrator_agent_gateway_circuit_open gauge\n",
            "joysafeter_orchestrator_agent_gateway_circuit_open {}\n",
            "# TYPE joysafeter_orchestrator_agent_gateway_reconnects_total counter\n",
            "joysafeter_orchestrator_agent_gateway_reconnects_total {}\n",
            "# TYPE joysafeter_orchestrator_agent_gateway_rejections_total counter\n",
            "joysafeter_orchestrator_agent_gateway_rejections_total{{reason=\"circuit_open\"}} {}\n",
            "joysafeter_orchestrator_agent_gateway_rejections_total{{reason=\"inflight_limit\"}} {}\n",
            "joysafeter_orchestrator_agent_gateway_rejections_total{{reason=\"message_too_large\"}} {}\n"
        ),
        STREAM_CONNECTED.load(Ordering::Relaxed),
        COMMANDS_IN_FLIGHT.load(Ordering::Relaxed),
        CIRCUIT_OPEN.load(Ordering::Relaxed),
        RECONNECTS.load(Ordering::Relaxed),
        CIRCUIT_REJECTIONS.load(Ordering::Relaxed),
        INFLIGHT_REJECTIONS.load(Ordering::Relaxed),
        OVERSIZE_REJECTIONS.load(Ordering::Relaxed),
    )
}
