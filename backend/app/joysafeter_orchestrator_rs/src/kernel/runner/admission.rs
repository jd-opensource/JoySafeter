use chrono::{DateTime, Utc};

use crate::ids::SandboxId;
use crate::kernel::runtime_auth::{
    AuthenticatedRunner, RunnerAuthenticationServiceError, RunnerAuthenticator, VerifiedRunner,
};

const SETUP_ACK_V1: &str = "setup_ack_v1";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct RunnerProtocolFailure {
    code: &'static str,
    message: &'static str,
}

impl RunnerProtocolFailure {
    pub(crate) fn code(&self) -> &'static str {
        self.code
    }

    pub(crate) fn message(&self) -> &'static str {
        self.message
    }
}

pub(crate) fn validate_runner_protocol(
    capabilities: &[String],
) -> Result<(), RunnerProtocolFailure> {
    if capabilities
        .iter()
        .any(|capability| capability == SETUP_ACK_V1)
    {
        return Ok(());
    }
    Err(RunnerProtocolFailure {
        code: "runner_protocol_incompatible",
        message: "runner protocol is missing setup_ack_v1",
    })
}

#[derive(Clone)]
pub(crate) struct RunnerAdmissionService {
    authenticator: RunnerAuthenticator,
}

impl RunnerAdmissionService {
    pub(crate) fn new(authenticator: RunnerAuthenticator) -> Self {
        Self { authenticator }
    }

    pub(crate) async fn verify_identity(
        &self,
        sandbox_id: SandboxId,
        presented_token: Option<&str>,
        now: DateTime<Utc>,
    ) -> Result<VerifiedRunner, RunnerAuthenticationServiceError> {
        self.authenticator
            .verify(sandbox_id, presented_token, now)
            .await
    }

    pub(crate) async fn accept(
        &self,
        verified: &VerifiedRunner,
    ) -> Result<AuthenticatedRunner, RunnerAuthenticationServiceError> {
        self.authenticator.record_connection(verified).await
    }
}
