use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use sqlx::PgPool;

use crate::db::queries::{self, NetworkPolicyAckOutcome, NetworkPolicyGeneration};
use crate::ids::SandboxId;
use crate::kernel::ha::{NetworkPolicyRequest, NetworkPolicyRequestQueue};
use crate::sandbox::provider::SandboxProvider;

#[derive(Clone)]
pub struct XdsAuthorityState {
    inner: Arc<XdsAuthorityInner>,
}

struct XdsAuthorityInner {
    standalone: bool,
    epoch: AtomicU64,
    advertised: AtomicBool,
    ready: AtomicBool,
    apply_lock: Arc<tokio::sync::Mutex<()>>,
}

#[derive(Clone)]
pub struct XdsAuthorityGuard {
    state: XdsAuthorityState,
    epoch: u64,
}

impl XdsAuthorityState {
    pub fn standalone() -> Self {
        Self {
            inner: Arc::new(XdsAuthorityInner {
                standalone: true,
                epoch: AtomicU64::new(1),
                advertised: AtomicBool::new(true),
                ready: AtomicBool::new(true),
                apply_lock: Arc::new(tokio::sync::Mutex::new(())),
            }),
        }
    }

    pub fn managed() -> Self {
        Self {
            inner: Arc::new(XdsAuthorityInner {
                standalone: false,
                epoch: AtomicU64::new(0),
                advertised: AtomicBool::new(false),
                ready: AtomicBool::new(false),
                apply_lock: Arc::new(tokio::sync::Mutex::new(())),
            }),
        }
    }

    pub fn advertise(&self) -> XdsAuthorityGuard {
        if self.inner.standalone {
            return XdsAuthorityGuard {
                state: self.clone(),
                epoch: self.inner.epoch.load(Ordering::Acquire),
            };
        }
        self.inner.ready.store(false, Ordering::Release);
        self.inner.advertised.store(true, Ordering::Release);
        let epoch = self.inner.epoch.fetch_add(1, Ordering::AcqRel) + 1;
        XdsAuthorityGuard {
            state: self.clone(),
            epoch,
        }
    }

    pub fn revoke(&self) {
        if self.inner.standalone {
            return;
        }
        self.inner.ready.store(false, Ordering::Release);
        self.inner.advertised.store(false, Ordering::Release);
        self.inner.epoch.fetch_add(1, Ordering::AcqRel);
    }

    pub fn advertised_guard(&self) -> Option<XdsAuthorityGuard> {
        if !self.inner.advertised.load(Ordering::Acquire) {
            return None;
        }
        Some(XdsAuthorityGuard {
            state: self.clone(),
            epoch: self.inner.epoch.load(Ordering::Acquire),
        })
    }

    pub fn ready_guard(&self) -> Option<XdsAuthorityGuard> {
        if !self.is_ready() {
            return None;
        }
        self.advertised_guard()
    }

    pub fn is_ready(&self) -> bool {
        self.inner.ready.load(Ordering::Acquire) && self.inner.advertised.load(Ordering::Acquire)
    }

    pub async fn lock_application(&self) -> tokio::sync::OwnedMutexGuard<()> {
        self.inner.apply_lock.clone().lock_owned().await
    }

    pub fn mark_ready(&self, guard: &XdsAuthorityGuard) -> bool {
        if !guard.is_current() {
            return false;
        }
        self.inner.ready.store(true, Ordering::Release);
        guard.is_current()
    }
}

impl XdsAuthorityGuard {
    pub fn epoch(&self) -> u64 {
        self.epoch
    }

    pub fn is_current(&self) -> bool {
        self.state.inner.advertised.load(Ordering::Acquire)
            && self.state.inner.epoch.load(Ordering::Acquire) == self.epoch
    }
}

pub async fn wait_for_network_policy_ready(
    pool: &PgPool,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    timeout: Duration,
) -> anyhow::Result<NetworkPolicyAckOutcome> {
    let deadline = tokio::time::Instant::now() + timeout;
    loop {
        let sandbox = queries::get_sandbox(pool, sandbox_id)
            .await
            .context("failed to read sandbox network policy state")?
            .ok_or_else(|| {
                anyhow::anyhow!("sandbox {sandbox_id} disappeared while awaiting xDS")
            })?;
        if sandbox.networking_policy_hash.as_deref() != Some(&generation.policy_hash)
            || sandbox.networking_policy_version != generation.policy_version
        {
            anyhow::bail!(
                "sandbox {sandbox_id} network policy generation changed while awaiting xDS authority"
            );
        }
        match sandbox.networking_status.as_str() {
            "ready"
                if sandbox.networking_applied_hash.as_deref() == Some(&generation.policy_hash)
                    && sandbox.networking_applied_version == Some(generation.policy_version) =>
            {
                return Ok(NetworkPolicyAckOutcome::AlreadyReady)
            }
            "nacked" | "failed" => anyhow::bail!(
                "xDS authority rejected sandbox {sandbox_id} policy: {}",
                sandbox
                    .networking_last_error
                    .as_deref()
                    .unwrap_or("unspecified error")
            ),
            _ => {}
        }
        if tokio::time::Instant::now() >= deadline {
            anyhow::bail!(
                "timed out waiting for xDS authority to apply sandbox {sandbox_id} policy generation {}",
                generation.policy_version
            );
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}

pub async fn ensure_network_policy_ready(
    pool: &PgPool,
    provider: &dyn SandboxProvider,
    queue: Option<&dyn NetworkPolicyRequestQueue>,
    authority: &XdsAuthorityState,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
    llm_egress_allowed_hosts: &[String],
    timeout: Duration,
) -> anyhow::Result<NetworkPolicyAckOutcome> {
    if let Some(queue) = queue {
        queue
            .publish(NetworkPolicyRequest::reconcile(
                sandbox_id,
                generation.clone(),
            ))
            .await
            .context("failed to request xDS authority reconciliation")?;
        return wait_for_network_policy_ready(pool, sandbox_id, generation, timeout).await;
    }
    let _application_lock = authority.lock_application().await;
    let guard = authority
        .ready_guard()
        .ok_or_else(|| anyhow::anyhow!("local xDS authority is not ready"))?;
    match crate::kernel::sandbox_resolver::apply_sandbox_networking_generation_as_authority(
        pool,
        provider,
        sandbox_id,
        generation,
        llm_egress_allowed_hosts,
        &guard,
    )
    .await?
    {
        crate::kernel::sandbox_resolver::NetworkingReconcileOutcome::Refreshed { .. } => {
            Ok(NetworkPolicyAckOutcome::Applied)
        }
        crate::kernel::sandbox_resolver::NetworkingReconcileOutcome::AlreadyReady { .. } => {
            Ok(NetworkPolicyAckOutcome::AlreadyReady)
        }
        crate::kernel::sandbox_resolver::NetworkingReconcileOutcome::NotLimited => {
            anyhow::bail!("sandbox {sandbox_id} no longer requires limited networking")
        }
    }
}

#[cfg(test)]
mod tests {
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
