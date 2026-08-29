use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use super::authority::AuthorityState;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct XdsMetricsSnapshot {
    pub authority_state: AuthorityState,
    pub authority_epoch: u64,
    pub active_streams: u64,
    pub authentication_failures: u64,
    pub acks: u64,
    pub nacks: u64,
    pub reconcile_successes: u64,
    pub reconcile_failures: u64,
}

pub struct XdsMetrics {
    authority_state: Mutex<AuthorityState>,
    active_streams: AtomicU64,
    authentication_failures: AtomicU64,
    acks: AtomicU64,
    nacks: AtomicU64,
    reconcile_successes: AtomicU64,
    reconcile_failures: AtomicU64,
}

impl Default for XdsMetrics {
    fn default() -> Self {
        Self {
            authority_state: Mutex::new(AuthorityState::Standby),
            active_streams: AtomicU64::new(0),
            authentication_failures: AtomicU64::new(0),
            acks: AtomicU64::new(0),
            nacks: AtomicU64::new(0),
            reconcile_successes: AtomicU64::new(0),
            reconcile_failures: AtomicU64::new(0),
        }
    }
}

impl XdsMetrics {
    pub fn set_authority_state(&self, state: AuthorityState) {
        *self
            .authority_state
            .lock()
            .expect("xDS authority metric lock poisoned") = state;
    }

    pub fn stream_opened(&self) {
        self.active_streams.fetch_add(1, Ordering::Relaxed);
    }

    pub fn stream_closed(&self) {
        self.active_streams
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                Some(value.saturating_sub(1))
            })
            .ok();
    }

    pub fn authentication_failed(&self) {
        self.authentication_failures.fetch_add(1, Ordering::Relaxed);
    }

    pub fn ack_recorded(&self) {
        self.acks.fetch_add(1, Ordering::Relaxed);
    }

    pub fn nack_recorded(&self) {
        self.nacks.fetch_add(1, Ordering::Relaxed);
    }

    pub fn reconcile_completed(&self, success: bool) {
        if success {
            self.reconcile_successes.fetch_add(1, Ordering::Relaxed);
        } else {
            self.reconcile_failures.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub fn snapshot(&self) -> XdsMetricsSnapshot {
        let authority_state = *self
            .authority_state
            .lock()
            .expect("xDS authority metric lock poisoned");
        let authority_epoch = match authority_state {
            AuthorityState::Acquired(epoch)
            | AuthorityState::Recovering(epoch)
            | AuthorityState::Ready(epoch)
            | AuthorityState::Revoking(epoch) => epoch.get(),
            AuthorityState::Standby | AuthorityState::Stopped => 0,
        };
        XdsMetricsSnapshot {
            authority_state,
            authority_epoch,
            active_streams: self.active_streams.load(Ordering::Relaxed),
            authentication_failures: self.authentication_failures.load(Ordering::Relaxed),
            acks: self.acks.load(Ordering::Relaxed),
            nacks: self.nacks.load(Ordering::Relaxed),
            reconcile_successes: self.reconcile_successes.load(Ordering::Relaxed),
            reconcile_failures: self.reconcile_failures.load(Ordering::Relaxed),
        }
    }
}
