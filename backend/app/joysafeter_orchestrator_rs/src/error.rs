/// Unified error types for the orchestrator.
#[derive(Debug, thiserror::Error)]
pub enum OrchestratorError {
    #[error("database error: {0}")]
    Database(#[from] sqlx::Error),

    #[error("gRPC error: {0}")]
    Grpc(#[from] tonic::Status),

    #[error("redis error: {0}")]
    Redis(#[from] redis::RedisError),

    #[error("docker error: {0}")]
    Docker(#[from] bollard::errors::Error),

    #[error("json error: {0}")]
    Json(#[from] serde_json::Error),

    #[error("config error: {0}")]
    Config(String),

    #[error("sandbox error: {0}")]
    Sandbox(String),

    #[error("task error: {0}")]
    Task(String),

    #[error("internal error: {0}")]
    Internal(String),
}

pub type Result<T> = std::result::Result<T, OrchestratorError>;
