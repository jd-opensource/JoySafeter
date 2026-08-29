use std::collections::HashMap;
use std::time::Duration;

use envoy_types::pb::envoy::config::core::v3::Node;
use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_client::AggregatedDiscoveryServiceClient,
    aggregated_discovery_service_server::AggregatedDiscoveryServiceServer, DeltaDiscoveryRequest,
    DeltaDiscoveryResponse,
};
use envoy_types::pb::google::protobuf::Any;
use joysafeter_orchestrator::ids::SandboxId;
use joysafeter_orchestrator::xds::authority::XdsAuthority;
use joysafeter_orchestrator::xds::control_plane::{NodeVisibility, XdsControlPlane};
use joysafeter_orchestrator::xds::delivery::{DeliveryAttempt, DeliveryRequest};
use joysafeter_orchestrator::xds::model::DeliveryGeneration;
use joysafeter_orchestrator::xds::model::{ManagedXdsResource, ResourceOwner, ResourceType};
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
use tonic::transport::Server;

fn resource(sandbox_id: SandboxId, resource_type: ResourceType, name: &str) -> ManagedXdsResource {
    resource_with_payload(sandbox_id, resource_type, name, name.as_bytes())
}

fn resource_with_payload(
    sandbox_id: SandboxId,
    resource_type: ResourceType,
    name: &str,
    payload: &[u8],
) -> ManagedXdsResource {
    ManagedXdsResource {
        name: name.to_string(),
        resource_type,
        owner: ResourceOwner::Sandbox(sandbox_id),
        payload: Any {
            type_url: resource_type.type_url().to_string(),
            value: payload.to_vec(),
        },
    }
}

fn delivery_request(epoch: u64, sandbox_id: SandboxId, suffix: &str) -> DeliveryRequest {
    DeliveryRequest {
        authority_epoch: epoch,
        sandbox_id,
        generation: DeliveryGeneration {
            policy_hash: format!("policy-{suffix}"),
            policy_version: 1,
        },
    }
}

fn request(
    node_id: Option<&str>,
    resource_type: ResourceType,
    response_nonce: impl Into<String>,
) -> DeltaDiscoveryRequest {
    DeltaDiscoveryRequest {
        node: node_id.map(|id| Node {
            id: id.to_string(),
            ..Default::default()
        }),
        type_url: resource_type.type_url().to_string(),
        response_nonce: response_nonce.into(),
        ..Default::default()
    }
}

fn request_with_initial_versions<I, K, V>(
    node_id: &str,
    resource_type: ResourceType,
    initial_resource_versions: I,
) -> DeltaDiscoveryRequest
where
    I: IntoIterator<Item = (K, V)>,
    K: Into<String>,
    V: Into<String>,
{
    DeltaDiscoveryRequest {
        node: Some(Node {
            id: node_id.to_string(),
            ..Default::default()
        }),
        type_url: resource_type.type_url().to_string(),
        initial_resource_versions: initial_resource_versions
            .into_iter()
            .map(|(name, version)| (name.into(), version.into()))
            .collect::<HashMap<_, _>>(),
        ..Default::default()
    }
}

async fn next_response(
    responses: &mut tonic::Streaming<DeltaDiscoveryResponse>,
    label: &str,
) -> DeltaDiscoveryResponse {
    tokio::time::timeout(Duration::from_secs(2), responses.message())
        .await
        .unwrap_or_else(|_| panic!("timed out waiting for {label}"))
        .unwrap_or_else(|error| panic!("failed reading {label}: {error}"))
        .unwrap_or_else(|| panic!("ADS stream ended before {label}"))
}

async fn assert_no_response(responses: &mut tonic::Streaming<DeltaDiscoveryResponse>, label: &str) {
    assert!(
        tokio::time::timeout(Duration::from_millis(50), responses.message())
            .await
            .is_err(),
        "received unexpected {label}"
    );
}

async fn complete_initial_listener_delivery(
    control_plane: &XdsControlPlane,
    client: &mut AggregatedDiscoveryServiceClient<tonic::transport::Channel>,
    attempt: DeliveryAttempt,
    node_id: &str,
    listener_name: &str,
) -> String {
    let (request_tx, request_rx) = tokio::sync::mpsc::channel(2);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open initial ADS stream")
        .into_inner();
    request_tx
        .send(request(Some(node_id), ResourceType::Listener, ""))
        .await
        .expect("subscribe to initial listener delivery");

    let response = next_response(&mut responses, "initial listener delivery").await;
    assert_eq!(response.resources.len(), 1);
    assert_eq!(response.resources[0].name, listener_name);
    let delivered_version = response.resources[0].version.clone();
    request_tx
        .send(request(None, ResourceType::Listener, response.nonce))
        .await
        .expect("ACK initial listener delivery");
    control_plane
        .wait_for_delivery(attempt, Duration::from_secs(1))
        .await
        .expect("initial listener delivery completes");

    drop(request_tx);
    drop(responses);
    delivered_version
}

async fn start_control_plane() -> (
    XdsControlPlane,
    AggregatedDiscoveryServiceClient<tonic::transport::Channel>,
    oneshot::Sender<()>,
    tokio::task::JoinHandle<Result<(), tonic::transport::Error>>,
    u64,
) {
    start_control_plane_with_visibility(NodeVisibility::Unscoped).await
}

async fn start_control_plane_with_visibility(
    visibility: NodeVisibility,
) -> (
    XdsControlPlane,
    AggregatedDiscoveryServiceClient<tonic::transport::Channel>,
    oneshot::Sender<()>,
    tokio::task::JoinHandle<Result<(), tonic::transport::Error>>,
    u64,
) {
    let authority = XdsAuthority::managed();
    let recovery = authority.begin_staging().expect("begin staging");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");
    let epoch = recovery.epoch();
    let control_plane = XdsControlPlane::new(authority, visibility);
    let listener = TcpListener::bind("127.0.0.1:0").await.expect("bind ADS");
    let address = listener.local_addr().expect("ADS address");
    let (shutdown_tx, shutdown_rx) = oneshot::channel();
    let service = control_plane.ads_service();
    let server = tokio::spawn(async move {
        Server::builder()
            .add_service(AggregatedDiscoveryServiceServer::from_arc(service))
            .serve_with_incoming_shutdown(TcpListenerStream::new(listener), async {
                let _ = shutdown_rx.await;
            })
            .await
    });
    let channel = tonic::transport::Endpoint::from_shared(format!("http://{address}"))
        .expect("ADS endpoint")
        .connect()
        .await
        .expect("connect ADS client");
    (
        control_plane,
        AggregatedDiscoveryServiceClient::new(channel),
        shutdown_tx,
        server,
        epoch,
    )
}

#[tokio::test]
async fn ads_node_move_removes_old_visibility_and_requires_new_node_ack() {
    let (control_plane, mut node_a_client, shutdown_tx, server, epoch) =
        start_control_plane_with_visibility(NodeVisibility::NodeScoped).await;
    let mut node_b_client = node_a_client.clone();
    let sandbox_id = SandboxId::new();

    let (node_a_tx, node_a_rx) = tokio::sync::mpsc::channel(4);
    let mut node_a_responses = node_a_client
        .delta_aggregated_resources(ReceiverStream::new(node_a_rx))
        .await
        .expect("open node-a ADS stream")
        .into_inner();
    node_a_tx
        .send(request(Some("node-a"), ResourceType::Listener, ""))
        .await
        .expect("subscribe node-a LDS");
    next_response(&mut node_a_responses, "initial node-a LDS").await;

    assert!(control_plane
        .assign_sandbox_node(sandbox_id, "node-a")
        .await
        .expect("assign node-a")
        .is_none());
    let initial = control_plane
        .publish_sandbox_resources(
            DeliveryRequest {
                authority_epoch: epoch,
                sandbox_id,
                generation: DeliveryGeneration {
                    policy_hash: "policy-1".to_string(),
                    policy_version: 1,
                },
            },
            vec![resource(
                sandbox_id,
                ResourceType::Listener,
                "listener-moved",
            )],
        )
        .await
        .expect("publish initial node policy")
        .expect("initial publication requires delivery");
    let initial_update = next_response(&mut node_a_responses, "initial node-a update").await;
    node_a_tx
        .send(request(None, ResourceType::Listener, initial_update.nonce))
        .await
        .expect("ACK initial node-a update");
    control_plane
        .wait_for_delivery(initial, Duration::from_secs(1))
        .await
        .expect("initial node-a delivery");

    let movement = control_plane
        .assign_sandbox_node(sandbox_id, "node-b")
        .await
        .expect("move sandbox to node-b")
        .expect("node movement requires fresh delivery");
    let old_node_removal = next_response(&mut node_a_responses, "old-node removal").await;
    let (node_b_tx, node_b_rx) = tokio::sync::mpsc::channel(4);
    let mut node_b_responses = node_b_client
        .delta_aggregated_resources(ReceiverStream::new(node_b_rx))
        .await
        .expect("open node-b ADS stream")
        .into_inner();
    node_b_tx
        .send(request_with_initial_versions(
            "node-b",
            ResourceType::Listener,
            [("listener-moved", "1")],
        ))
        .await
        .expect("reconnect node-b with matching stale placement version");
    let new_node_update = next_response(&mut node_b_responses, "new-node publication").await;
    assert_eq!(old_node_removal.removed_resources, vec!["listener-moved"]);
    assert!(old_node_removal.resources.is_empty());
    assert_eq!(new_node_update.resources.len(), 1);
    assert_eq!(new_node_update.resources[0].name, "listener-moved");

    node_a_tx
        .send(request(
            None,
            ResourceType::Listener,
            old_node_removal.nonce,
        ))
        .await
        .expect("ACK old-node removal");
    assert!(
        control_plane
            .wait_for_delivery(movement, Duration::from_millis(20))
            .await
            .is_err(),
        "old-node removal ACK must not complete movement"
    );
    node_b_tx
        .send(request(None, ResourceType::Listener, new_node_update.nonce))
        .await
        .expect("ACK new-node publication");
    control_plane
        .wait_for_delivery(movement, Duration::from_secs(1))
        .await
        .expect("new-node ACK completes movement");

    drop(node_a_tx);
    drop(node_b_tx);
    drop(node_a_responses);
    drop(node_b_responses);
    drop(node_a_client);
    drop(node_b_client);
    let _ = shutdown_tx.send(());
    server
        .await
        .expect("join ADS server")
        .expect("stop ADS server");
}

#[tokio::test]
async fn ads_requires_node_identity_on_the_first_request() {
    let (_control_plane, mut client, shutdown_tx, server, _epoch) = start_control_plane().await;
    let (request_tx, request_rx) = tokio::sync::mpsc::channel(2);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open ADS stream")
        .into_inner();

    request_tx
        .send(request(None, ResourceType::Listener, ""))
        .await
        .expect("send request");
    let error = responses
        .message()
        .await
        .expect_err("missing initial node id must close the stream");
    assert_eq!(error.code(), tonic::Code::InvalidArgument);

    let _ = shutdown_tx.send(());
    server
        .await
        .expect("join ADS server")
        .expect("stop ADS server");
}

#[tokio::test]
async fn ads_reconnect_reconciles_client_versions_and_removes_stale_resources() {
    let (control_plane, mut client, shutdown_tx, server, epoch) = start_control_plane().await;
    let sandbox_id = SandboxId::new();
    let attempt = control_plane
        .publish_sandbox_resources(
            delivery_request(epoch, sandbox_id, "reconnect-removal"),
            vec![resource(
                sandbox_id,
                ResourceType::Listener,
                "listener-current",
            )],
        )
        .await
        .expect("seed current listener")
        .expect("current listener requires delivery");
    let delivered_version = complete_initial_listener_delivery(
        &control_plane,
        &mut client,
        attempt,
        "node-a",
        "listener-current",
    )
    .await;

    let (request_tx, request_rx) = tokio::sync::mpsc::channel(2);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open ADS stream")
        .into_inner();
    request_tx
        .send(request_with_initial_versions(
            "node-a",
            ResourceType::Listener,
            [
                ("listener-current", delivered_version.as_str()),
                ("listener-stale", delivered_version.as_str()),
            ],
        ))
        .await
        .expect("subscribe with client versions");

    let response = next_response(&mut responses, "reconnect reconciliation").await;
    assert!(
        response.resources.is_empty(),
        "matching client resources must not be retransmitted"
    );
    assert_eq!(response.removed_resources, vec!["listener-stale"]);

    drop(request_tx);
    drop(responses);
    drop(client);
    let _ = shutdown_tx.send(());
    server
        .await
        .expect("join ADS server")
        .expect("stop ADS server");
}

#[tokio::test]
async fn ads_reconnect_retransmits_resources_with_mismatched_versions() {
    let (control_plane, mut client, shutdown_tx, server, epoch) = start_control_plane().await;
    let sandbox_id = SandboxId::new();
    let attempt = control_plane
        .publish_sandbox_resources(
            delivery_request(epoch, sandbox_id, "reconnect-upsert"),
            vec![resource(
                sandbox_id,
                ResourceType::Listener,
                "listener-current",
            )],
        )
        .await
        .expect("seed current listener")
        .expect("current listener requires delivery");
    let delivered_version = complete_initial_listener_delivery(
        &control_plane,
        &mut client,
        attempt,
        "node-a",
        "listener-current",
    )
    .await;
    let stale_version = format!("stale-{delivered_version}");

    let (request_tx, request_rx) = tokio::sync::mpsc::channel(2);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open ADS stream")
        .into_inner();
    request_tx
        .send(request_with_initial_versions(
            "node-a",
            ResourceType::Listener,
            [("listener-current", stale_version.as_str())],
        ))
        .await
        .expect("subscribe with stale client version");

    let response = next_response(&mut responses, "version mismatch reconciliation").await;
    assert_eq!(response.resources.len(), 1);
    assert_eq!(response.resources[0].name, "listener-current");
    assert_eq!(response.resources[0].version, delivered_version);
    assert!(response.removed_resources.is_empty());

    drop(request_tx);
    drop(responses);
    drop(client);
    let _ = shutdown_tx.send(());
    server
        .await
        .expect("join ADS server")
        .expect("stop ADS server");
}

#[tokio::test]
async fn ads_acknowledges_exact_changed_types_and_removal_quorum() {
    let (control_plane, mut client, shutdown_tx, server, epoch) = start_control_plane().await;
    let (request_tx, request_rx) = tokio::sync::mpsc::channel(8);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open ADS stream")
        .into_inner();

    request_tx
        .send(request(Some("node-a"), ResourceType::Cluster, ""))
        .await
        .expect("subscribe CDS");
    next_response(&mut responses, "initial CDS").await;
    request_tx
        .send(request(None, ResourceType::Listener, ""))
        .await
        .expect("subscribe LDS");
    next_response(&mut responses, "initial LDS").await;

    let sandbox_id = SandboxId::new();
    let attempt = control_plane
        .publish_sandbox_resources(
            DeliveryRequest {
                authority_epoch: epoch,
                sandbox_id,
                generation: DeliveryGeneration {
                    policy_hash: "policy-1".to_string(),
                    policy_version: 1,
                },
            },
            vec![
                resource(sandbox_id, ResourceType::Cluster, "cluster-a"),
                resource(sandbox_id, ResourceType::Listener, "listener-a"),
            ],
        )
        .await
        .expect("publish sandbox resources")
        .expect("changed resources require delivery");

    let cluster = next_response(&mut responses, "CDS update").await;
    let listener = next_response(&mut responses, "LDS update").await;
    assert_eq!(cluster.type_url, ResourceType::Cluster.type_url());
    assert_eq!(listener.type_url, ResourceType::Listener.type_url());

    request_tx
        .send(request(None, ResourceType::Cluster, cluster.nonce))
        .await
        .expect("ACK CDS");
    assert!(control_plane
        .wait_for_delivery(attempt, Duration::from_millis(20))
        .await
        .is_err());
    request_tx
        .send(request(None, ResourceType::Listener, listener.nonce))
        .await
        .expect("ACK LDS");
    control_plane
        .wait_for_delivery(attempt, Duration::from_secs(1))
        .await
        .expect("CDS and LDS quorum");

    let republished = control_plane
        .publish_sandbox_resources(
            DeliveryRequest {
                authority_epoch: epoch,
                sandbox_id,
                generation: DeliveryGeneration {
                    policy_hash: "policy-2".to_string(),
                    policy_version: 2,
                },
            },
            vec![
                resource(sandbox_id, ResourceType::Cluster, "cluster-a"),
                resource(sandbox_id, ResourceType::Listener, "listener-a"),
            ],
        )
        .await
        .expect("republish identical resources")
        .expect("a new durable generation requires fresh delivery proof");
    let cluster_reannouncement = next_response(&mut responses, "CDS reannouncement").await;
    let listener_reannouncement = next_response(&mut responses, "LDS reannouncement").await;
    request_tx
        .send(request(
            None,
            ResourceType::Cluster,
            cluster_reannouncement.nonce,
        ))
        .await
        .expect("ACK CDS reannouncement");
    request_tx
        .send(request(
            None,
            ResourceType::Listener,
            listener_reannouncement.nonce,
        ))
        .await
        .expect("ACK LDS reannouncement");
    control_plane
        .wait_for_delivery(republished, Duration::from_secs(1))
        .await
        .expect("identical resources still require exact-generation quorum");

    let listener_attempt = control_plane
        .publish_sandbox_resources(
            DeliveryRequest {
                authority_epoch: epoch,
                sandbox_id,
                generation: DeliveryGeneration {
                    policy_hash: "policy-3".to_string(),
                    policy_version: 3,
                },
            },
            vec![
                resource(sandbox_id, ResourceType::Cluster, "cluster-a"),
                resource_with_payload(
                    sandbox_id,
                    ResourceType::Listener,
                    "listener-a",
                    b"listener-a-v2",
                ),
            ],
        )
        .await
        .expect("publish listener-only update")
        .expect("listener change requires delivery");
    let listener_update = next_response(&mut responses, "listener-only update").await;
    assert_eq!(listener_update.type_url, ResourceType::Listener.type_url());
    assert_eq!(
        listener_update
            .resources
            .iter()
            .map(|resource| resource.name.as_str())
            .collect::<Vec<_>>(),
        vec!["listener-a"]
    );
    assert!(listener_update.removed_resources.is_empty());
    assert_no_response(&mut responses, "CDS response for listener-only update").await;
    request_tx
        .send(request(None, ResourceType::Listener, listener_update.nonce))
        .await
        .expect("ACK listener-only update");
    control_plane
        .wait_for_delivery(listener_attempt, Duration::from_secs(1))
        .await
        .expect("listener-only quorum");

    let removal = control_plane
        .remove_sandbox_resources(sandbox_id)
        .await
        .expect("publish sandbox removal")
        .expect("existing resources require removal delivery");
    let cluster_removal = next_response(&mut responses, "CDS removal").await;
    let listener_removal = next_response(&mut responses, "LDS removal").await;
    assert_eq!(cluster_removal.removed_resources, vec!["cluster-a"]);
    assert_eq!(listener_removal.removed_resources, vec!["listener-a"]);
    request_tx
        .send(request(None, ResourceType::Cluster, cluster_removal.nonce))
        .await
        .expect("ACK CDS removal");
    request_tx
        .send(request(
            None,
            ResourceType::Listener,
            listener_removal.nonce,
        ))
        .await
        .expect("ACK LDS removal");
    control_plane
        .wait_for_delivery(removal, Duration::from_secs(1))
        .await
        .expect("removal quorum");

    drop(request_tx);
    drop(responses);
    drop(client);
    let _ = shutdown_tx.send(());
    server
        .await
        .expect("join ADS server")
        .expect("stop ADS server");
}
