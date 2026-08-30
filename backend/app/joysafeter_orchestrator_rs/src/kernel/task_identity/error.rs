use super::material::TaskIdentityMaterialError;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub(crate) enum TaskIdentityContextError {
    #[error("task identity database operation failed")]
    Database,
    #[error("task identity project does not match")]
    ProjectMismatch,
    #[error("task identity requires project and session scope")]
    ScopeMissing,
    #[error("task identity requires an authenticated task actor")]
    ActorMissing,
    #[error(transparent)]
    Material(#[from] TaskIdentityMaterialError),
    #[error("task identity credential kind is invalid")]
    KindInvalid,
    #[error("task identity context is invalid")]
    ContextInvalid,
    #[error("task identity provider is disabled for a requested route")]
    ProviderDisabled,
    #[error("task identity has no trusted egress hosts")]
    NoTrustedHosts,
    #[error("task identity provider returned no injection targets")]
    EmptyInjection,
    #[error("task identity provider failed")]
    Provider,
    #[error("task identity provider returned a mismatched route")]
    RouteMismatch,
    #[error("task identity claim changed while locked")]
    ClaimConflict,
}
