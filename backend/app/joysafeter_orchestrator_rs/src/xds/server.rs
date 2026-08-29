use std::net::SocketAddr;
use std::sync::Arc;

use envoy_types::pb::envoy::service::discovery::v3::aggregated_discovery_service_server::AggregatedDiscoveryServiceServer;
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tracing::{error, info};

use crate::xds::transport::DeltaXdsServer;

pub async fn start_ads_server(
    addr: SocketAddr,
    service: Arc<DeltaXdsServer>,
) -> anyhow::Result<JoinHandle<()>> {
    let listener = TcpListener::bind(addr).await?;
    let local_addr = listener.local_addr()?;
    let handle = tokio::spawn(async move {
        info!(addr = %local_addr, "Envoy ADS server listening");
        if let Err(error) = tonic::transport::Server::builder()
            .tcp_keepalive(Some(std::time::Duration::from_secs(30)))
            .http2_keepalive_interval(Some(std::time::Duration::from_secs(30)))
            .http2_keepalive_timeout(Some(std::time::Duration::from_secs(10)))
            .add_service(AggregatedDiscoveryServiceServer::from_arc(service))
            .serve_with_incoming(TcpListenerStream::new(listener))
            .await
        {
            error!(%error, "ADS server stopped with an error");
        }
    });
    Ok(handle)
}
