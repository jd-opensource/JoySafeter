use thiserror::Error;

#[derive(Debug, Error)]
pub enum AgentdError {
    #[error("not found: {0}")]
    NotFound(String),
    #[error("already exists: {0}")]
    AlreadyExists(String),
    #[error("invalid input: {0}")]
    InvalidInput(String),
    #[error("database error: {0}")]
    Database(String),
    #[error("redis error: {0}")]
    Redis(String),
    #[error("sandbox error: {0}")]
    Sandbox(String),
    #[error("internal error: {0}")]
    Internal(String),
}
