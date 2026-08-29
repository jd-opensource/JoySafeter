use std::sync::Arc;
use std::time::Duration;

use envoy_types::pb::envoy::config::core::v3::Node;
use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_client::AggregatedDiscoveryServiceClient,
    aggregated_discovery_service_server::AggregatedDiscoveryServiceServer, DeltaDiscoveryRequest,
};
use joysafeter_orchestrator::xds::auth::{StaticTokenAdsAuthenticator, ADS_NODE_ID_HEADER};
use joysafeter_orchestrator::xds::transport::DeltaXdsServer;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
use tonic::metadata::MetadataValue;
use tonic::transport::Server;
use tonic::Request;

async fn spawn_server() -> (
    std::net::SocketAddr,
    oneshot::Sender<()>,
    tokio::task::JoinHandle<Result<(), tonic::transport::Error>>,
) {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind ADS contract listener");
    let address = listener.local_addr().expect("read ADS contract address");
    let authenticator = Arc::new(StaticTokenAdsAuthenticator::new("top-secret").unwrap());
    let service = DeltaXdsServer::new(authenticator);
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let task = tokio::spawn(async move {
        Server::builder()
            .add_service(AggregatedDiscoveryServiceServer::from_arc(service))
            .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                let _ = shutdown_rx.await;
            })
            .await
    });
    (address, shutdown_tx, task)
}

#[tokio::test]
async fn ads_rejects_missing_authentication_metadata() {
    let (address, shutdown_tx, task) = spawn_server().await;
    let channel = tonic::transport::Endpoint::from_shared(format!("http://{address}"))
        .unwrap()
        .connect()
        .await
        .unwrap();
    let mut client = AggregatedDiscoveryServiceClient::new(channel);
    let (_tx, rx) = tokio::sync::mpsc::channel(1);

    let error = client
        .delta_aggregated_resources(ReceiverStream::new(rx))
        .await
        .expect_err("ADS must reject missing credentials");

    assert_eq!(error.code(), tonic::Code::Unauthenticated);
    let _ = shutdown_tx.send(());
    task.await.unwrap().unwrap();
}

#[tokio::test]
async fn ads_rejects_node_id_that_differs_from_authenticated_identity() {
    let (address, shutdown_tx, task) = spawn_server().await;
    let channel = tonic::transport::Endpoint::from_shared(format!("http://{address}"))
        .unwrap()
        .connect()
        .await
        .unwrap();
    let mut client = AggregatedDiscoveryServiceClient::new(channel);
    let (tx, rx) = tokio::sync::mpsc::channel(1);
    let mut request = Request::new(ReceiverStream::new(rx));
    request.metadata_mut().insert(
        "authorization",
        MetadataValue::try_from("Bearer top-secret").unwrap(),
    );
    request.metadata_mut().insert(
        ADS_NODE_ID_HEADER,
        MetadataValue::try_from("node-a").unwrap(),
    );
    let mut stream = client
        .delta_aggregated_resources(request)
        .await
        .expect("authenticated ADS stream")
        .into_inner();

    tx.send(DeltaDiscoveryRequest {
        node: Some(Node {
            id: "node-b".to_string(),
            ..Default::default()
        }),
        type_url: "type.googleapis.com/envoy.config.listener.v3.Listener".to_string(),
        ..Default::default()
    })
    .await
    .unwrap();

    let error = tokio::time::timeout(Duration::from_secs(1), stream.message())
        .await
        .expect("server should reject mismatched node promptly")
        .expect_err("mismatched node must close with an error");
    assert_eq!(error.code(), tonic::Code::PermissionDenied);

    let _ = shutdown_tx.send(());
    task.await.unwrap().unwrap();
}
