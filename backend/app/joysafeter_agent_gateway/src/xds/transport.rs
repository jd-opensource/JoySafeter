use std::net::SocketAddr;
use std::sync::Arc;

use anyhow::Context;
use envoy_types::pb::envoy::service::discovery::v3::aggregated_discovery_service_server::AggregatedDiscoveryServiceServer;
use tokio::net::TcpListener;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::service::interceptor::InterceptedService;
use tonic::Request;
use tracing::info;

use crate::bootstrap::shutdown::ShutdownSignal;

use super::auth::XdsClientAuthenticator;
use super::control_plane::XdsControlPlane;
use super::metrics::XdsStreamRejection;

#[allow(clippy::result_large_err)] // tonic's interceptor closure must return tonic::Status.
pub async fn start_xds_server(
    addr: SocketAddr,
    service: XdsControlPlane,
    authenticator: Arc<dyn XdsClientAuthenticator>,
    shutdown: ShutdownSignal,
) -> anyhow::Result<JoinHandle<anyhow::Result<()>>> {
    let listener = TcpListener::bind(addr).await?;
    let metrics = service.metrics();
    let ads = AggregatedDiscoveryServiceServer::from_arc(service.ads_service());
    let authenticated_ads = InterceptedService::new(ads, move |mut request: Request<()>| {
        match authenticator.authenticate(&request) {
            Ok(principal) => {
                metrics.record_authenticated_stream();
                request.extensions_mut().insert(principal);
                Ok(request)
            }
            Err(error) => {
                metrics.record_rejected_stream(XdsStreamRejection::Unauthenticated);
                Err(error)
            }
        }
    });
    let handle = tokio::spawn(async move {
        info!(addr = %addr, "authenticated xDS server listening");
        tonic::transport::Server::builder()
            .add_service(authenticated_ads)
            .serve_with_incoming_shutdown(TcpListenerStream::new(listener), shutdown.wait())
            .await
            .with_context(|| format!("Agent Gateway xDS server failed on {addr}"))
    });
    Ok(handle)
}
