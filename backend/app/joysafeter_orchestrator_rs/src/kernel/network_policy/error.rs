use thiserror::Error;

use crate::xds::delivery::DeliveryWaitError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkPolicyFailureStatus {
    Nacked,
    Failed,
}

impl NetworkPolicyFailureStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Nacked => "nacked",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct NetworkPolicyFailurePersistence<'a> {
    pub status: NetworkPolicyFailureStatus,
    pub retryable: bool,
    pub nack_reason: Option<&'a str>,
}

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum NetworkPolicyApplyError {
    #[error("invalid network policy: {0}")]
    InvalidPolicy(String),
    #[error("xDS authority is unavailable")]
    AuthorityUnavailable,
    #[error("xDS authority changed during policy application")]
    AuthorityChanged,
    #[error("network policy generation was superseded")]
    GenerationSuperseded,
    #[error("sandbox is unavailable for network policy application: {0}")]
    SandboxUnavailable(String),
    #[error("network policy state read failed: {0}")]
    StateReadFailed(String),
    #[error("network policy runtime preparation failed: {0}")]
    RuntimePreparationFailed(String),
    #[error("network policy recovery state is invalid: {0}")]
    RecoveryStateInvalid(String),
    #[error("network policy material is unavailable: {0}")]
    MaterialUnavailable(String),
    #[error("xDS publication failed: {0}")]
    PublicationUnavailable(String),
    #[error("Envoy NACK'd {resource_type} xDS delivery: {reason}")]
    DeliveryNacked {
        resource_type: String,
        reason: String,
    },
    #[error("timed out waiting for exact Envoy xDS delivery")]
    DeliveryTimedOut,
    #[error("xDS delivery attempt was superseded")]
    DeliverySuperseded,
    #[error("Envoy socket preparation failed: {0}")]
    SocketPreparationFailed(String),
    #[error("Envoy socket did not become ready: {0}")]
    SocketNotReady(String),
    #[error("network policy application exceeded its deadline")]
    ApplyTimedOut,
}

impl NetworkPolicyApplyError {
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidPolicy(_) => "invalid_policy",
            Self::AuthorityUnavailable => "authority_unavailable",
            Self::AuthorityChanged => "authority_changed",
            Self::GenerationSuperseded => "generation_superseded",
            Self::SandboxUnavailable(_) => "sandbox_unavailable",
            Self::StateReadFailed(_) => "state_read_failed",
            Self::RuntimePreparationFailed(_) => "runtime_preparation_failed",
            Self::RecoveryStateInvalid(_) => "recovery_state_invalid",
            Self::MaterialUnavailable(_) => "material_unavailable",
            Self::PublicationUnavailable(_) => "publication_unavailable",
            Self::DeliveryNacked { .. } => "delivery_nacked",
            Self::DeliveryTimedOut => "delivery_timeout",
            Self::DeliverySuperseded => "delivery_superseded",
            Self::SocketPreparationFailed(_) => "socket_preparation_failed",
            Self::SocketNotReady(_) => "socket_not_ready",
            Self::ApplyTimedOut => "apply_timeout",
        }
    }

    pub fn persistence(&self) -> Option<NetworkPolicyFailurePersistence<'_>> {
        let failed = |retryable| NetworkPolicyFailurePersistence {
            status: NetworkPolicyFailureStatus::Failed,
            retryable,
            nack_reason: None,
        };
        match self {
            Self::InvalidPolicy(_) | Self::RecoveryStateInvalid(_) => Some(failed(false)),
            Self::AuthorityUnavailable
            | Self::AuthorityChanged
            | Self::StateReadFailed(_)
            | Self::RuntimePreparationFailed(_)
            | Self::MaterialUnavailable(_)
            | Self::PublicationUnavailable(_)
            | Self::DeliveryTimedOut
            | Self::SocketPreparationFailed(_)
            | Self::SocketNotReady(_)
            | Self::ApplyTimedOut => Some(failed(true)),
            Self::DeliveryNacked { reason, .. } => Some(NetworkPolicyFailurePersistence {
                status: NetworkPolicyFailureStatus::Nacked,
                retryable: false,
                nack_reason: Some(reason),
            }),
            Self::GenerationSuperseded | Self::SandboxUnavailable(_) | Self::DeliverySuperseded => {
                None
            }
        }
    }
}

impl From<DeliveryWaitError> for NetworkPolicyApplyError {
    fn from(error: DeliveryWaitError) -> Self {
        match error {
            DeliveryWaitError::Nacked {
                resource_type,
                reason,
                ..
            } => Self::DeliveryNacked {
                resource_type: format!("{resource_type:?}"),
                reason,
            },
            DeliveryWaitError::TimedOut { .. } => Self::DeliveryTimedOut,
            DeliveryWaitError::Superseded { .. } => Self::DeliverySuperseded,
        }
    }
}
