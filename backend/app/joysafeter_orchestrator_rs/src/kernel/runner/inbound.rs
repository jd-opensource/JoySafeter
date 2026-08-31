use async_trait::async_trait;

use crate::grpc::proto::RunnerMessage;

/// Application-owned input port for the Runner bidirectional session.
#[async_trait]
pub(crate) trait RunnerInbound: Send {
    async fn message(&mut self) -> anyhow::Result<Option<RunnerMessage>>;
}
