use std::sync::{Arc, Mutex};

use super::metrics::XdsMetrics;
use super::model::AuthorityEpoch;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum AuthorityState {
    Standby,
    Acquired(AuthorityEpoch),
    Recovering(AuthorityEpoch),
    Ready(AuthorityEpoch),
    Revoking(AuthorityEpoch),
    Stopped,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct AuthorityFence {
    epoch: AuthorityEpoch,
}

impl AuthorityFence {
    pub fn epoch(self) -> AuthorityEpoch {
        self.epoch
    }
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
#[error("illegal xDS authority transition from {from:?} via {operation}")]
pub struct AuthorityTransitionError {
    from: AuthorityState,
    operation: &'static str,
}

pub struct AuthorityStateMachine {
    state: AuthorityState,
    highest_epoch: AuthorityEpoch,
}

impl Default for AuthorityStateMachine {
    fn default() -> Self {
        Self {
            state: AuthorityState::Standby,
            highest_epoch: AuthorityEpoch::new(0),
        }
    }
}

impl AuthorityStateMachine {
    pub fn standalone(epoch: AuthorityEpoch) -> Self {
        Self {
            state: AuthorityState::Ready(epoch),
            highest_epoch: epoch,
        }
    }

    pub fn state(&self) -> AuthorityState {
        self.state
    }

    pub fn current_epoch(&self) -> Option<AuthorityEpoch> {
        match self.state {
            AuthorityState::Acquired(epoch)
            | AuthorityState::Recovering(epoch)
            | AuthorityState::Ready(epoch)
            | AuthorityState::Revoking(epoch) => Some(epoch),
            AuthorityState::Standby | AuthorityState::Stopped => None,
        }
    }

    pub fn next_epoch(&self) -> AuthorityEpoch {
        AuthorityEpoch::new(self.highest_epoch.get().saturating_add(1))
    }

    pub fn is_advertised(&self) -> bool {
        matches!(
            self.state,
            AuthorityState::Acquired(_) | AuthorityState::Recovering(_) | AuthorityState::Ready(_)
        )
    }

    pub fn acquire(&mut self, epoch: AuthorityEpoch) -> Result<(), AuthorityTransitionError> {
        if self.state != AuthorityState::Standby || epoch <= self.highest_epoch {
            return Err(self.illegal("acquire"));
        }
        self.highest_epoch = epoch;
        self.state = AuthorityState::Acquired(epoch);
        Ok(())
    }

    pub fn begin_recovery(&mut self) -> Result<(), AuthorityTransitionError> {
        let AuthorityState::Acquired(epoch) = self.state else {
            return Err(self.illegal("begin_recovery"));
        };
        self.state = AuthorityState::Recovering(epoch);
        Ok(())
    }

    pub fn mark_ready(&mut self) -> Result<(), AuthorityTransitionError> {
        let AuthorityState::Recovering(epoch) = self.state else {
            return Err(self.illegal("mark_ready"));
        };
        self.state = AuthorityState::Ready(epoch);
        Ok(())
    }

    pub fn begin_revoke(&mut self) -> Result<(), AuthorityTransitionError> {
        let epoch = match self.state {
            AuthorityState::Acquired(epoch)
            | AuthorityState::Recovering(epoch)
            | AuthorityState::Ready(epoch) => epoch,
            _ => return Err(self.illegal("begin_revoke")),
        };
        self.state = AuthorityState::Revoking(epoch);
        Ok(())
    }

    pub fn complete_revoke(&mut self) -> Result<(), AuthorityTransitionError> {
        if !matches!(self.state, AuthorityState::Revoking(_)) {
            return Err(self.illegal("complete_revoke"));
        }
        self.state = AuthorityState::Standby;
        Ok(())
    }

    pub fn stop(&mut self) {
        self.state = AuthorityState::Stopped;
    }

    pub fn ready_fence(&self) -> Option<AuthorityFence> {
        match self.state {
            AuthorityState::Ready(epoch) => Some(AuthorityFence { epoch }),
            _ => None,
        }
    }

    fn illegal(&self, operation: &'static str) -> AuthorityTransitionError {
        AuthorityTransitionError {
            from: self.state,
            operation,
        }
    }
}

#[derive(Clone)]
pub struct XdsAuthorityState {
    inner: Arc<XdsAuthorityInner>,
}

struct XdsAuthorityInner {
    standalone: bool,
    machine: Mutex<AuthorityStateMachine>,
    metrics: Arc<XdsMetrics>,
    apply_lock: Arc<tokio::sync::Mutex<()>>,
}

#[derive(Clone)]
pub struct XdsAuthorityGuard {
    state: XdsAuthorityState,
    epoch: AuthorityEpoch,
}

impl XdsAuthorityState {
    pub fn standalone() -> Self {
        Self::standalone_with_metrics(Arc::new(XdsMetrics::default()))
    }

    pub fn standalone_with_metrics(metrics: Arc<XdsMetrics>) -> Self {
        let epoch = AuthorityEpoch::new(1);
        metrics.set_authority_state(AuthorityState::Ready(epoch));
        Self {
            inner: Arc::new(XdsAuthorityInner {
                standalone: true,
                machine: Mutex::new(AuthorityStateMachine::standalone(epoch)),
                metrics,
                apply_lock: Arc::new(tokio::sync::Mutex::new(())),
            }),
        }
    }

    pub fn managed() -> Self {
        Self::managed_with_metrics(Arc::new(XdsMetrics::default()))
    }

    pub fn managed_with_metrics(metrics: Arc<XdsMetrics>) -> Self {
        metrics.set_authority_state(AuthorityState::Standby);
        Self {
            inner: Arc::new(XdsAuthorityInner {
                standalone: false,
                machine: Mutex::new(AuthorityStateMachine::default()),
                metrics,
                apply_lock: Arc::new(tokio::sync::Mutex::new(())),
            }),
        }
    }

    pub fn advertise(&self) -> XdsAuthorityGuard {
        if self.inner.standalone {
            return XdsAuthorityGuard {
                state: self.clone(),
                epoch: self
                    .inner
                    .machine
                    .lock()
                    .expect("xDS authority state lock poisoned")
                    .current_epoch()
                    .expect("standalone authority has an epoch"),
            };
        }
        let mut machine = self
            .inner
            .machine
            .lock()
            .expect("xDS authority state lock poisoned");
        let epoch = machine.next_epoch();
        machine
            .acquire(epoch)
            .expect("xDS authority must be standby before advertise");
        machine
            .begin_recovery()
            .expect("newly acquired xDS authority must enter recovery");
        self.inner.metrics.set_authority_state(machine.state());
        XdsAuthorityGuard {
            state: self.clone(),
            epoch,
        }
    }

    pub fn revoke(&self) {
        if self.inner.standalone {
            return;
        }
        let mut machine = self
            .inner
            .machine
            .lock()
            .expect("xDS authority state lock poisoned");
        if machine.begin_revoke().is_ok() {
            self.inner.metrics.set_authority_state(machine.state());
            machine
                .complete_revoke()
                .expect("revoking xDS authority must return to standby");
            self.inner.metrics.set_authority_state(machine.state());
        }
    }

    pub fn advertised_guard(&self) -> Option<XdsAuthorityGuard> {
        let machine = self
            .inner
            .machine
            .lock()
            .expect("xDS authority state lock poisoned");
        if !machine.is_advertised() {
            return None;
        }
        Some(XdsAuthorityGuard {
            state: self.clone(),
            epoch: machine
                .current_epoch()
                .expect("advertised xDS authority has an epoch"),
        })
    }

    pub fn ready_guard(&self) -> Option<XdsAuthorityGuard> {
        if !self.is_ready() {
            return None;
        }
        self.advertised_guard()
    }

    pub fn is_ready(&self) -> bool {
        matches!(
            self.inner
                .machine
                .lock()
                .expect("xDS authority state lock poisoned")
                .state(),
            AuthorityState::Ready(_)
        )
    }

    pub async fn lock_application(&self) -> tokio::sync::OwnedMutexGuard<()> {
        self.inner.apply_lock.clone().lock_owned().await
    }

    pub fn mark_ready(&self, guard: &XdsAuthorityGuard) -> bool {
        if !guard.is_current() {
            return false;
        }
        if self.inner.standalone {
            return true;
        }
        let mut machine = self
            .inner
            .machine
            .lock()
            .expect("xDS authority state lock poisoned");
        let ready = machine.mark_ready().is_ok();
        if ready {
            self.inner.metrics.set_authority_state(machine.state());
        }
        ready
    }
}

impl XdsAuthorityGuard {
    pub fn epoch(&self) -> u64 {
        self.epoch.get()
    }

    pub fn authority_epoch(&self) -> AuthorityEpoch {
        self.epoch
    }

    pub fn is_current(&self) -> bool {
        let machine = self
            .state
            .inner
            .machine
            .lock()
            .expect("xDS authority state lock poisoned");
        machine.is_advertised() && machine.current_epoch() == Some(self.epoch)
    }
}

#[cfg(test)]
mod runtime_tests {
    use super::{XdsAuthorityGuard, XdsAuthorityState};

    #[test]
    fn managed_authority_is_not_ready_until_recovery_completes() {
        let state = XdsAuthorityState::managed();
        let guard = state.advertise();
        assert!(guard.is_current());
        assert!(!state.is_ready());
        assert!(state.mark_ready(&guard));
        assert!(state.is_ready());
    }

    #[test]
    fn revoked_authority_invalidates_existing_guard() {
        let state = XdsAuthorityState::managed();
        let guard = state.advertise();
        assert!(state.mark_ready(&guard));
        state.revoke();
        assert!(!guard.is_current());
        assert!(!state.is_ready());
        assert!(!state.mark_ready(&guard));
    }

    #[test]
    fn standalone_authority_is_always_ready() {
        let state = XdsAuthorityState::standalone();
        let guard: XdsAuthorityGuard = state
            .ready_guard()
            .expect("standalone authority must always be ready");
        assert!(state.is_ready());
        assert!(guard.is_current());
    }
}
