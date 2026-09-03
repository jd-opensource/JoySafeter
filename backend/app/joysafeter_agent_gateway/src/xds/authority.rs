use std::sync::{Arc, Mutex as StdMutex};
use std::time::{Duration, Instant};

use thiserror::Error;
use tokio::sync::watch;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AuthorityPhase {
    Standby,
    Staging { epoch: u64 },
    RecoveryServing { epoch: u64 },
    Ready { epoch: u64 },
    Revoked { epoch: u64 },
}

impl AuthorityPhase {
    pub fn epoch(self) -> Option<u64> {
        match self {
            Self::Standby => None,
            Self::Staging { epoch }
            | Self::RecoveryServing { epoch }
            | Self::Ready { epoch }
            | Self::Revoked { epoch } => Some(epoch),
        }
    }

    pub fn serves_ads(self) -> bool {
        matches!(self, Self::RecoveryServing { .. } | Self::Ready { .. })
    }
}

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum AuthorityError {
    #[error("invalid xDS authority transition from {from:?} to {target}")]
    InvalidTransition {
        from: AuthorityPhase,
        target: &'static str,
    },
    #[error("xDS authority guard for epoch {guard_epoch} is stale in phase {phase:?}")]
    StaleGuard {
        guard_epoch: u64,
        phase: AuthorityPhase,
    },
}

#[derive(Clone)]
pub struct XdsAuthority {
    inner: Arc<XdsAuthorityInner>,
}

struct XdsAuthorityInner {
    phase: watch::Sender<AuthorityPhase>,
    lifecycle: StdMutex<AuthorityLifecycle>,
}

#[derive(Debug, Default)]
struct AuthorityLifecycle {
    recovery_started_at: Option<Instant>,
    last_ready_recovery_duration: Duration,
    last_revoked_recovery_duration: Duration,
    ready_recovery_total: u64,
    revoked_recovery_total: u64,
}

#[derive(Debug, Clone)]
pub(crate) struct AuthorityMetricsSnapshot {
    pub phase: AuthorityPhase,
    pub current_recovery_duration: Duration,
    pub last_ready_recovery_duration: Duration,
    pub last_revoked_recovery_duration: Duration,
    pub ready_recovery_total: u64,
    pub revoked_recovery_total: u64,
}

#[derive(Clone)]
pub struct RecoveryAuthorityGuard {
    authority: XdsAuthority,
    epoch: u64,
}

#[derive(Clone)]
pub struct MutationAuthorityGuard {
    authority: XdsAuthority,
    epoch: u64,
}

impl XdsAuthority {
    pub fn standalone() -> Self {
        Self::new()
    }

    fn new() -> Self {
        let (phase, _receiver) = watch::channel(AuthorityPhase::Standby);
        Self {
            inner: Arc::new(XdsAuthorityInner {
                phase,
                lifecycle: StdMutex::new(AuthorityLifecycle::default()),
            }),
        }
    }

    pub fn phase(&self) -> AuthorityPhase {
        *self.inner.phase.borrow()
    }

    pub fn subscribe(&self) -> watch::Receiver<AuthorityPhase> {
        self.inner.phase.subscribe()
    }

    pub fn validate_delivery_epoch(&self, epoch: u64) -> Result<(), AuthorityError> {
        let phase = self.phase();
        if phase.serves_ads() && phase.epoch() == Some(epoch) {
            Ok(())
        } else {
            Err(AuthorityError::StaleGuard {
                guard_epoch: epoch,
                phase,
            })
        }
    }

    pub fn begin_staging(&self) -> Result<RecoveryAuthorityGuard, AuthorityError> {
        let epoch = self.phase().epoch().unwrap_or(0).saturating_add(1);
        self.begin_staging_at(epoch)
    }

    /// Enter staging using the cluster-global Kubernetes Lease transition.
    pub fn begin_staging_at(
        &self,
        requested_epoch: u64,
    ) -> Result<RecoveryAuthorityGuard, AuthorityError> {
        let started_at = Instant::now();
        let mut lifecycle = self
            .inner
            .lifecycle
            .lock()
            .expect("xDS authority lifecycle poisoned");
        let mut result = None;
        self.inner.phase.send_if_modified(|phase| {
            let epoch = match *phase {
                AuthorityPhase::Standby if requested_epoch > 0 => requested_epoch,
                AuthorityPhase::Revoked { epoch } if requested_epoch > epoch => requested_epoch,
                current => {
                    result = Some(Err(AuthorityError::InvalidTransition {
                        from: current,
                        target: "Staging",
                    }));
                    return false;
                }
            };
            lifecycle.recovery_started_at = Some(started_at);
            *phase = AuthorityPhase::Staging { epoch };
            result = Some(Ok(RecoveryAuthorityGuard {
                authority: self.clone(),
                epoch,
            }));
            true
        });
        result.expect("authority transition closure must set a result")
    }

    pub fn begin_recovery_serving(
        &self,
        guard: &RecoveryAuthorityGuard,
    ) -> Result<(), AuthorityError> {
        if !guard.belongs_to(self) {
            return Err(AuthorityError::StaleGuard {
                guard_epoch: guard.epoch,
                phase: self.phase(),
            });
        }
        let mut result = None;
        self.inner.phase.send_if_modified(|phase| match *phase {
            AuthorityPhase::Staging { epoch } if epoch == guard.epoch => {
                *phase = AuthorityPhase::RecoveryServing { epoch: guard.epoch };
                result = Some(Ok(()));
                true
            }
            AuthorityPhase::RecoveryServing { epoch } if epoch == guard.epoch => {
                result = Some(Ok(()));
                false
            }
            _ => {
                result = Some(Err(AuthorityError::StaleGuard {
                    guard_epoch: guard.epoch,
                    phase: *phase,
                }));
                false
            }
        });
        result.expect("authority transition closure must set a result")
    }

    pub fn mark_ready(&self, guard: &RecoveryAuthorityGuard) -> Result<(), AuthorityError> {
        if !guard.belongs_to(self) {
            return Err(AuthorityError::StaleGuard {
                guard_epoch: guard.epoch,
                phase: self.phase(),
            });
        }
        let mut lifecycle = self
            .inner
            .lifecycle
            .lock()
            .expect("xDS authority lifecycle poisoned");
        let mut result = None;
        self.inner.phase.send_if_modified(|phase| {
            if *phase == (AuthorityPhase::RecoveryServing { epoch: guard.epoch }) {
                let duration = lifecycle
                    .recovery_started_at
                    .take()
                    .map(|started_at| started_at.elapsed())
                    .unwrap_or_default();
                lifecycle.last_ready_recovery_duration = duration;
                lifecycle.ready_recovery_total = lifecycle.ready_recovery_total.saturating_add(1);
                *phase = AuthorityPhase::Ready { epoch: guard.epoch };
                result = Some(Ok(()));
                true
            } else {
                result = Some(Err(AuthorityError::StaleGuard {
                    guard_epoch: guard.epoch,
                    phase: *phase,
                }));
                false
            }
        });
        result.expect("authority transition closure must set a result")
    }

    pub fn mark_ready_epoch(&self, epoch: u64) -> Result<(), AuthorityError> {
        if self.phase() == (AuthorityPhase::Ready { epoch }) {
            return Ok(());
        }
        let guard = RecoveryAuthorityGuard {
            authority: self.clone(),
            epoch,
        };
        self.mark_ready(&guard)
    }

    pub fn revoke(&self) -> Result<(), AuthorityError> {
        let mut lifecycle = self
            .inner
            .lifecycle
            .lock()
            .expect("xDS authority lifecycle poisoned");
        let mut result = None;
        self.inner.phase.send_if_modified(|phase| {
            let Some(epoch) = phase.epoch() else {
                result = Some(Err(AuthorityError::InvalidTransition {
                    from: *phase,
                    target: "Revoked",
                }));
                return false;
            };
            if matches!(*phase, AuthorityPhase::Revoked { .. }) {
                result = Some(Ok(()));
                return false;
            }
            if matches!(
                *phase,
                AuthorityPhase::Staging { .. } | AuthorityPhase::RecoveryServing { .. }
            ) {
                let duration = lifecycle
                    .recovery_started_at
                    .take()
                    .map(|started_at| started_at.elapsed())
                    .unwrap_or_default();
                lifecycle.last_revoked_recovery_duration = duration;
                lifecycle.revoked_recovery_total =
                    lifecycle.revoked_recovery_total.saturating_add(1);
            }
            *phase = AuthorityPhase::Revoked { epoch };
            result = Some(Ok(()));
            true
        });
        result.expect("authority transition closure must set a result")
    }

    pub fn mutation_guard(&self) -> Option<MutationAuthorityGuard> {
        let epoch = match self.phase() {
            AuthorityPhase::RecoveryServing { epoch } | AuthorityPhase::Ready { epoch } => epoch,
            _ => return None,
        };
        Some(MutationAuthorityGuard {
            authority: self.clone(),
            epoch,
        })
    }

    pub(crate) fn metrics_snapshot(&self) -> AuthorityMetricsSnapshot {
        let phase = self.phase();
        let lifecycle = self
            .inner
            .lifecycle
            .lock()
            .expect("xDS authority lifecycle poisoned");
        let current_recovery_duration = if matches!(
            phase,
            AuthorityPhase::Staging { .. } | AuthorityPhase::RecoveryServing { .. }
        ) {
            lifecycle
                .recovery_started_at
                .map(|started_at| started_at.elapsed())
                .unwrap_or_default()
        } else {
            Duration::ZERO
        };
        AuthorityMetricsSnapshot {
            phase,
            current_recovery_duration,
            last_ready_recovery_duration: lifecycle.last_ready_recovery_duration,
            last_revoked_recovery_duration: lifecycle.last_revoked_recovery_duration,
            ready_recovery_total: lifecycle.ready_recovery_total,
            revoked_recovery_total: lifecycle.revoked_recovery_total,
        }
    }
}

impl RecoveryAuthorityGuard {
    fn belongs_to(&self, authority: &XdsAuthority) -> bool {
        Arc::ptr_eq(&self.authority.inner, &authority.inner)
    }

    pub fn epoch(&self) -> u64 {
        self.epoch
    }

    pub fn validate(&self) -> Result<(), AuthorityError> {
        let phase = self.authority.phase();
        if matches!(
            phase,
            AuthorityPhase::Staging { epoch } | AuthorityPhase::RecoveryServing { epoch }
                if epoch == self.epoch
        ) {
            Ok(())
        } else {
            Err(AuthorityError::StaleGuard {
                guard_epoch: self.epoch,
                phase,
            })
        }
    }
}

impl MutationAuthorityGuard {
    pub fn epoch(&self) -> u64 {
        self.epoch
    }

    pub fn validate(&self) -> Result<(), AuthorityError> {
        let phase = self.authority.phase();
        if matches!(
            phase,
            AuthorityPhase::RecoveryServing { epoch } | AuthorityPhase::Ready { epoch }
                if epoch == self.epoch
        ) {
            Ok(())
        } else {
            Err(AuthorityError::StaleGuard {
                guard_epoch: self.epoch,
                phase,
            })
        }
    }
}

#[cfg(test)]
#[path = "../../tests/unit/xds/authority_test.rs"]
mod tests;
