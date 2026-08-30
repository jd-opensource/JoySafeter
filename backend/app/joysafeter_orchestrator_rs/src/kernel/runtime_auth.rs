use std::sync::Arc;

use async_trait::async_trait;
use chrono::{DateTime, Utc};
use sha2::{Digest, Sha256};
use subtle::ConstantTimeEq;

use crate::ids::{SandboxId, SessionId};

#[derive(Clone)]
pub(crate) struct StoredRunnerAuth {
    pub(crate) state: String,
    pub(crate) token_digest: Option<String>,
    pub(crate) expires_at: Option<DateTime<Utc>>,
    pub(crate) sandbox_status: String,
    pub(crate) linked_session_id: Option<SessionId>,
}

impl std::fmt::Debug for StoredRunnerAuth {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("StoredRunnerAuth")
            .field("state", &self.state)
            .field(
                "token_digest",
                &self.token_digest.as_ref().map(|_| "<redacted>"),
            )
            .field("expires_at", &self.expires_at)
            .field("sandbox_status", &self.sandbox_status)
            .field("linked_session_id", &self.linked_session_id)
            .finish()
    }
}

#[async_trait]
pub(crate) trait RunnerAuthStore: Send + Sync {
    async fn load(&self, sandbox_id: SandboxId) -> anyhow::Result<Option<StoredRunnerAuth>>;

    async fn mark_connected_if_current(
        &self,
        sandbox_id: SandboxId,
        expected: &StoredRunnerAuth,
    ) -> anyhow::Result<bool>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AuthenticatedRunner {
    pub(crate) sandbox_status: String,
    pub(crate) linked_session_id: Option<SessionId>,
}

#[derive(Debug, thiserror::Error)]
pub(crate) enum RunnerAuthenticationServiceError {
    #[error(transparent)]
    Rejected(#[from] RunnerAuthenticationError),
    #[error("runner authentication state changed during connection")]
    StateChanged,
    #[error("runner authentication store failed")]
    Store(#[source] anyhow::Error),
}

#[derive(Clone)]
pub(crate) struct RunnerAuthenticator {
    store: Arc<dyn RunnerAuthStore>,
}

impl RunnerAuthenticator {
    pub(crate) fn new(store: Arc<dyn RunnerAuthStore>) -> Self {
        Self { store }
    }

    pub(crate) async fn authenticate_and_record_connection(
        &self,
        sandbox_id: SandboxId,
        presented_token: Option<&str>,
        now: DateTime<Utc>,
    ) -> Result<AuthenticatedRunner, RunnerAuthenticationServiceError> {
        let stored = self
            .store
            .load(sandbox_id)
            .await
            .map_err(RunnerAuthenticationServiceError::Store)?
            .ok_or(RunnerAuthenticationError::UnknownSandbox)?;
        authenticate_runner(
            Some(RunnerAuthRecord {
                state: &stored.state,
                token_digest: stored.token_digest.as_deref(),
                expires_at: stored.expires_at,
                sandbox_status: &stored.sandbox_status,
            }),
            presented_token,
            now,
        )?;
        if !self
            .store
            .mark_connected_if_current(sandbox_id, &stored)
            .await
            .map_err(RunnerAuthenticationServiceError::Store)?
        {
            return Err(RunnerAuthenticationServiceError::StateChanged);
        }
        Ok(AuthenticatedRunner {
            sandbox_status: stored.sandbox_status,
            linked_session_id: stored.linked_session_id,
        })
    }
}

#[derive(Clone, Copy)]
pub(crate) struct RunnerAuthRecord<'a> {
    pub(crate) state: &'a str,
    pub(crate) token_digest: Option<&'a str>,
    pub(crate) expires_at: Option<DateTime<Utc>>,
    pub(crate) sandbox_status: &'a str,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub(crate) enum RunnerAuthenticationError {
    #[error("unknown sandbox")]
    UnknownSandbox,
    #[error("sandbox is not available for runner attachment")]
    SandboxUnavailable,
    #[error("runner authentication state is invalid")]
    InvalidState,
    #[error("runner authentication has been revoked")]
    Revoked,
    #[error("runner admission has expired")]
    AdmissionExpired,
    #[error("runner credential is missing from authoritative state")]
    MissingExpectedCredential,
    #[error("runner did not present a credential")]
    MissingPresentedCredential,
    #[error("runner credential does not match")]
    CredentialMismatch,
}

pub(crate) fn runner_token_digest(token: &str) -> String {
    hex::encode(Sha256::digest(token.as_bytes()))
}

pub(crate) fn egress_proxy_token(config: Option<&serde_json::Value>) -> Option<String> {
    config?
        .get("egress_proxy_token")?
        .as_str()
        .filter(|token| !token.trim().is_empty())
        .map(ToOwned::to_owned)
}

pub(crate) fn authenticate_runner(
    record: Option<RunnerAuthRecord<'_>>,
    presented_token: Option<&str>,
    now: DateTime<Utc>,
) -> Result<(), RunnerAuthenticationError> {
    let record = record.ok_or(RunnerAuthenticationError::UnknownSandbox)?;
    if !matches!(
        record.sandbox_status,
        "creating" | "provisioning" | "pooled" | "idle" | "running"
    ) {
        return Err(RunnerAuthenticationError::SandboxUnavailable);
    }

    match record.state {
        "admission" => match record.expires_at {
            Some(expires_at) if expires_at > now => {}
            Some(_) => return Err(RunnerAuthenticationError::AdmissionExpired),
            None => return Err(RunnerAuthenticationError::InvalidState),
        },
        "active" if record.expires_at.is_none() => {}
        "active" => return Err(RunnerAuthenticationError::InvalidState),
        "revoked" => return Err(RunnerAuthenticationError::Revoked),
        _ => return Err(RunnerAuthenticationError::InvalidState),
    }

    let expected_digest = record
        .token_digest
        .filter(|digest| !digest.is_empty())
        .ok_or(RunnerAuthenticationError::MissingExpectedCredential)?;
    let presented_token = presented_token
        .filter(|token| !token.is_empty())
        .ok_or(RunnerAuthenticationError::MissingPresentedCredential)?;
    let presented_digest = runner_token_digest(presented_token);
    if expected_digest
        .as_bytes()
        .ct_eq(presented_digest.as_bytes())
        .unwrap_u8()
        == 0
    {
        return Err(RunnerAuthenticationError::CredentialMismatch);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    use async_trait::async_trait;
    use chrono::{Duration, Utc};
    use uuid::Uuid;

    use super::{
        authenticate_runner, egress_proxy_token, runner_token_digest, RunnerAuthRecord,
        RunnerAuthStore, RunnerAuthenticationError, RunnerAuthenticationServiceError,
        RunnerAuthenticator, StoredRunnerAuth,
    };

    #[test]
    fn reads_only_non_empty_persisted_egress_proxy_tokens() {
        assert_eq!(
            egress_proxy_token(Some(&serde_json::json!({"egress_proxy_token": "secret"}))),
            Some("secret".to_string())
        );
        assert_eq!(
            egress_proxy_token(Some(&serde_json::json!({"egress_proxy_token": "  "}))),
            None
        );
        assert_eq!(egress_proxy_token(None), None);
    }
    use crate::ids::SandboxId;

    struct FakeRunnerAuthStore {
        record: Option<StoredRunnerAuth>,
        mark_result: bool,
        mark_calls: AtomicUsize,
    }

    #[async_trait]
    impl RunnerAuthStore for FakeRunnerAuthStore {
        async fn load(&self, _sandbox_id: SandboxId) -> anyhow::Result<Option<StoredRunnerAuth>> {
            Ok(self.record.clone())
        }

        async fn mark_connected_if_current(
            &self,
            _sandbox_id: SandboxId,
            _expected: &StoredRunnerAuth,
        ) -> anyhow::Result<bool> {
            self.mark_calls.fetch_add(1, Ordering::SeqCst);
            Ok(self.mark_result)
        }
    }

    fn stored_active(token: &str) -> StoredRunnerAuth {
        StoredRunnerAuth {
            state: "active".to_string(),
            token_digest: Some(runner_token_digest(token)),
            expires_at: None,
            sandbox_status: "running".to_string(),
            linked_session_id: None,
        }
    }

    #[test]
    fn unknown_sandbox_is_rejected_even_with_non_empty_token() {
        let now = Utc::now();

        assert_eq!(
            authenticate_runner(None, Some("attacker-token"), now),
            Err(RunnerAuthenticationError::UnknownSandbox)
        );
    }

    #[test]
    fn missing_expected_credential_is_rejected() {
        let now = Utc::now();
        let record = RunnerAuthRecord {
            state: "active",
            token_digest: None,
            expires_at: None,
            sandbox_status: "running",
        };

        assert_eq!(
            authenticate_runner(Some(record), Some("presented-token"), now),
            Err(RunnerAuthenticationError::MissingExpectedCredential)
        );
    }

    #[test]
    fn empty_presented_token_is_rejected() {
        let now = Utc::now();
        let digest = runner_token_digest("expected-token");
        let record = RunnerAuthRecord {
            state: "active",
            token_digest: Some(&digest),
            expires_at: None,
            sandbox_status: "running",
        };

        assert_eq!(
            authenticate_runner(Some(record), None, now),
            Err(RunnerAuthenticationError::MissingPresentedCredential)
        );
        assert_eq!(
            authenticate_runner(Some(record), Some(""), now),
            Err(RunnerAuthenticationError::MissingPresentedCredential)
        );
    }

    #[test]
    fn mismatched_token_is_rejected() {
        let now = Utc::now();
        let digest = runner_token_digest("expected-token");
        let record = RunnerAuthRecord {
            state: "active",
            token_digest: Some(&digest),
            expires_at: None,
            sandbox_status: "running",
        };

        assert_eq!(
            authenticate_runner(Some(record), Some("wrong-token"), now),
            Err(RunnerAuthenticationError::CredentialMismatch)
        );
    }

    #[test]
    fn valid_unexpired_staged_admission_is_accepted() {
        let now = Utc::now();
        let digest = runner_token_digest("expected-token");
        let record = RunnerAuthRecord {
            state: "admission",
            token_digest: Some(&digest),
            expires_at: Some(now + Duration::minutes(1)),
            sandbox_status: "creating",
        };

        assert_eq!(
            authenticate_runner(Some(record), Some("expected-token"), now),
            Ok(())
        );
    }

    #[test]
    fn expired_staged_admission_is_rejected() {
        let now = Utc::now();
        let digest = runner_token_digest("expected-token");
        let record = RunnerAuthRecord {
            state: "admission",
            token_digest: Some(&digest),
            expires_at: Some(now - Duration::seconds(1)),
            sandbox_status: "creating",
        };

        assert_eq!(
            authenticate_runner(Some(record), Some("expected-token"), now),
            Err(RunnerAuthenticationError::AdmissionExpired)
        );
    }

    #[test]
    fn malformed_and_revoked_auth_states_are_rejected() {
        let now = Utc::now();
        let digest = runner_token_digest("expected-token");

        for record in [
            RunnerAuthRecord {
                state: "admission",
                token_digest: Some(&digest),
                expires_at: None,
                sandbox_status: "creating",
            },
            RunnerAuthRecord {
                state: "active",
                token_digest: Some(&digest),
                expires_at: Some(now + Duration::minutes(1)),
                sandbox_status: "running",
            },
            RunnerAuthRecord {
                state: "revoked",
                token_digest: None,
                expires_at: None,
                sandbox_status: "destroyed",
            },
        ] {
            assert!(authenticate_runner(Some(record), Some("expected-token"), now).is_err());
        }
    }

    #[test]
    fn terminal_sandbox_is_rejected_even_with_valid_active_token() {
        let now = Utc::now();
        let digest = runner_token_digest("expected-token");
        let record = RunnerAuthRecord {
            state: "active",
            token_digest: Some(&digest),
            expires_at: None,
            sandbox_status: "error",
        };

        assert_eq!(
            authenticate_runner(Some(record), Some("expected-token"), now),
            Err(RunnerAuthenticationError::SandboxUnavailable)
        );
    }

    #[tokio::test]
    async fn valid_authentication_records_connection_once() {
        let store = Arc::new(FakeRunnerAuthStore {
            record: Some(stored_active("expected-token")),
            mark_result: true,
            mark_calls: AtomicUsize::new(0),
        });
        let authenticator = RunnerAuthenticator::new(store.clone());

        let authenticated = authenticator
            .authenticate_and_record_connection(
                SandboxId::from_uuid(Uuid::now_v7()),
                Some("expected-token"),
                Utc::now(),
            )
            .await
            .expect("valid runner authentication");

        assert_eq!(authenticated.sandbox_status, "running");
        assert_eq!(store.mark_calls.load(Ordering::SeqCst), 1);
    }

    #[tokio::test]
    async fn rejected_authentication_does_not_record_connection() {
        let store = Arc::new(FakeRunnerAuthStore {
            record: Some(stored_active("expected-token")),
            mark_result: true,
            mark_calls: AtomicUsize::new(0),
        });
        let authenticator = RunnerAuthenticator::new(store.clone());

        let error = authenticator
            .authenticate_and_record_connection(
                SandboxId::from_uuid(Uuid::now_v7()),
                Some("wrong-token"),
                Utc::now(),
            )
            .await
            .expect_err("invalid token must fail");

        assert!(matches!(
            error,
            RunnerAuthenticationServiceError::Rejected(
                RunnerAuthenticationError::CredentialMismatch
            )
        ));
        assert_eq!(store.mark_calls.load(Ordering::SeqCst), 0);
    }

    #[tokio::test]
    async fn concurrent_auth_state_change_fails_closed() {
        let store = Arc::new(FakeRunnerAuthStore {
            record: Some(stored_active("expected-token")),
            mark_result: false,
            mark_calls: AtomicUsize::new(0),
        });
        let authenticator = RunnerAuthenticator::new(store.clone());

        let error = authenticator
            .authenticate_and_record_connection(
                SandboxId::from_uuid(Uuid::now_v7()),
                Some("expected-token"),
                Utc::now(),
            )
            .await
            .expect_err("changed auth state must fail");

        assert!(matches!(
            error,
            RunnerAuthenticationServiceError::StateChanged
        ));
        assert_eq!(store.mark_calls.load(Ordering::SeqCst), 1);
    }
}
