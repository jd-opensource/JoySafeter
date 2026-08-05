use std::sync::atomic::{AtomicU32, AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;

pub struct RuntimeConfig {
    pub idle_timeout_sec: AtomicU64,
    pub stopped_max_age_sec: AtomicU64,
    pub heartbeat_timeout_sec: AtomicU64,
    pub sandbox_failure_threshold: AtomicU32,
    pub pool_min_size: AtomicUsize,
    pub pool_max_age_sec: AtomicU64,
    pub event_batch_max_size: AtomicUsize,
    pub event_batch_max_delay_ms: AtomicU64,
}

pub type SharedRuntimeConfig = Arc<RuntimeConfig>;

impl RuntimeConfig {
    pub fn idle_timeout_sec(&self) -> u64 {
        self.idle_timeout_sec.load(Ordering::Relaxed)
    }

    pub fn stopped_max_age_sec(&self) -> u64 {
        self.stopped_max_age_sec.load(Ordering::Relaxed)
    }

    pub fn heartbeat_timeout_sec(&self) -> u64 {
        self.heartbeat_timeout_sec.load(Ordering::Relaxed)
    }

    pub fn sandbox_failure_threshold(&self) -> u32 {
        self.sandbox_failure_threshold.load(Ordering::Relaxed)
    }

    pub fn pool_min_size(&self) -> usize {
        self.pool_min_size.load(Ordering::Relaxed)
    }

    pub fn pool_max_age_sec(&self) -> u64 {
        self.pool_max_age_sec.load(Ordering::Relaxed)
    }

    pub fn event_batch_max_size(&self) -> usize {
        self.event_batch_max_size.load(Ordering::Relaxed)
    }

    pub fn event_batch_max_delay_ms(&self) -> u64 {
        self.event_batch_max_delay_ms.load(Ordering::Relaxed)
    }
}
