use std::pin::Pin;
use std::sync::Arc;

use futures::Stream;
use tokio::sync::Semaphore;
use tokio_stream::StreamExt as _;
use tonic::{Request, Response, Status, Streaming};

use crate::grpc::proto::agent_bridge_server::AgentBridge;
use crate::grpc::proto::{OrchestratorMessage, RunnerMessage};
use crate::kernel::runner::RunnerSessionCoordinator;

/// Tonic adapter for the closed Runner wire protocol.
pub(crate) struct RunnerTransport {
    coordinator: Arc<RunnerSessionCoordinator>,
    connection_semaphore: Arc<Semaphore>,
}

impl RunnerTransport {
    pub(crate) fn new(coordinator: Arc<RunnerSessionCoordinator>, max_connections: usize) -> Self {
        Self {
            coordinator,
            connection_semaphore: Arc::new(Semaphore::new(max_connections)),
        }
    }
}

#[tonic::async_trait]
impl AgentBridge for RunnerTransport {
    type SessionStream =
        Pin<Box<dyn Stream<Item = Result<OrchestratorMessage, Status>> + Send + 'static>>;

    async fn session(
        &self,
        request: Request<Streaming<RunnerMessage>>,
    ) -> Result<Response<Self::SessionStream>, Status> {
        let connection_permit = self
            .connection_semaphore
            .clone()
            .try_acquire_owned()
            .map_err(|_| Status::resource_exhausted("Too many concurrent connections"))?;
        let outbound = self
            .coordinator
            .open_session(request.into_inner(), connection_permit)
            .await;

        Ok(Response::new(Box::pin(outbound.map(Ok))))
    }
}
