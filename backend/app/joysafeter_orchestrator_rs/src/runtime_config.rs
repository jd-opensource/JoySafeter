use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};

/// Runtime-tunable configuration with atomic reads.
///
/// Mirrors the Python `RuntimeConfig`. Values can be updated without
/// restarting the process (via SIGHUP handler).
pub struct RuntimeConfig {
    idle_timeout_sec: AtomicU64,
    stopped_max_age_sec: AtomicU64,
    heartbeat_timeout_sec: AtomicU64,
    sandbox_failure_threshold: AtomicU32,
    pool_min_size: AtomicU64,
    pool_max_age_sec: AtomicU64,
    event_batch_max_size: AtomicU64,
    event_batch_max_delay_ms: AtomicU64,
}

impl RuntimeConfig {
    pub fn new(
        idle_timeout_sec: u64,
        stopped_max_age_sec: u64,
        heartbeat_timeout_sec: u64,
        sandbox_failure_threshold: u32,
        pool_min_size: u64,
        pool_max_age_sec: u64,
        event_batch_max_size: u64,
        event_batch_max_delay_ms: u64,
    ) -> Self {
        Self {
            idle_timeout_sec: AtomicU64::new(idle_timeout_sec),
            stopped_max_age_sec: AtomicU64::new(stopped_max_age_sec),
            heartbeat_timeout_sec: AtomicU64::new(heartbeat_timeout_sec),
            sandbox_failure_threshold: AtomicU32::new(sandbox_failure_threshold),
            pool_min_size: AtomicU64::new(pool_min_size),
            pool_max_age_sec: AtomicU64::new(pool_max_age_sec),
            event_batch_max_size: AtomicU64::new(event_batch_max_size),
            event_batch_max_delay_ms: AtomicU64::new(event_batch_max_delay_ms),
        }
    }

    pub fn from_config(config: &crate::config::JoySafeterConfig) -> Self {
        Self::new(
            config.sandbox_idle_timeout,
            config.sandbox_stopped_ttl,
            config.heartbeat_ttl,
            config.sandbox_failure_threshold,
            config.sandbox_pool_min_size as u64,
            config.sandbox_pool_max_age,
            config.event_batch_max_size as u64,
            config.event_batch_max_delay_ms,
        )
    }

    // Getters
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
    pub fn pool_min_size(&self) -> u64 {
        self.pool_min_size.load(Ordering::Relaxed)
    }
    pub fn pool_max_age_sec(&self) -> u64 {
        self.pool_max_age_sec.load(Ordering::Relaxed)
    }
    pub fn event_batch_max_size(&self) -> u64 {
        self.event_batch_max_size.load(Ordering::Relaxed)
    }
    pub fn event_batch_max_delay_ms(&self) -> u64 {
        self.event_batch_max_delay_ms.load(Ordering::Relaxed)
    }

    /// Update all values atomically (called from SIGHUP handler).
    pub fn update(
        &self,
        idle_timeout_sec: u64,
        stopped_max_age_sec: u64,
        heartbeat_timeout_sec: u64,
        sandbox_failure_threshold: u32,
        pool_min_size: u64,
        pool_max_age_sec: u64,
        event_batch_max_size: u64,
        event_batch_max_delay_ms: u64,
    ) {
        self.idle_timeout_sec
            .store(idle_timeout_sec, Ordering::Relaxed);
        self.stopped_max_age_sec
            .store(stopped_max_age_sec, Ordering::Relaxed);
        self.heartbeat_timeout_sec
            .store(heartbeat_timeout_sec, Ordering::Relaxed);
        self.sandbox_failure_threshold
            .store(sandbox_failure_threshold, Ordering::Relaxed);
        self.pool_min_size.store(pool_min_size, Ordering::Relaxed);
        self.pool_max_age_sec
            .store(pool_max_age_sec, Ordering::Relaxed);
        self.event_batch_max_size
            .store(event_batch_max_size, Ordering::Relaxed);
        self.event_batch_max_delay_ms
            .store(event_batch_max_delay_ms, Ordering::Relaxed);
    }
}
