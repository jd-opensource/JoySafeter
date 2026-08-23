use thiserror::Error;

use crate::ids::{SandboxId, SessionId};

#[derive(Debug, Error)]
pub enum RuntimeFreshnessError {
    #[error("runtime generation changed: expected {expected}, actual {actual}")]
    GenerationChanged { expected: i64, actual: i64 },
    #[error("session binding is invalid for {session_id}: {reason}")]
    SessionBindingInvalid {
        session_id: SessionId,
        reason: &'static str,
    },
    #[error("runtime restart required for sandbox {sandbox_id}")]
    RuntimeRestartRequired { sandbox_id: SandboxId },
    #[error("runtime ownership conflict: {0}")]
    Conflict(String),
    #[error("runtime cleanup failed: {0}")]
    CleanupFailed(String),
    #[error(transparent)]
    Database(#[from] sqlx::Error),
}
