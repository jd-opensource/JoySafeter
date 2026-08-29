use std::collections::HashMap;
use std::net::{Ipv4Addr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

use envoy_types::pb::envoy::config::core::v3::Node;
use envoy_types::pb::envoy::service::discovery::v3::{
    aggregated_discovery_service_client::AggregatedDiscoveryServiceClient,
    aggregated_discovery_service_server::AggregatedDiscoveryServiceServer, DeltaDiscoveryRequest,
    DeltaDiscoveryResponse,
};
use envoy_types::pb::google::protobuf::Any;
use envoy_types::pb::google::rpc::Status as RpcStatus;
use joysafeter_orchestrator::ids::SandboxId;
use joysafeter_orchestrator::xds::auth::{SharedTokenAuthenticator, XdsAuthKeyring};
use joysafeter_orchestrator::xds::authority::{AuthorityPhase, XdsAuthority};
use joysafeter_orchestrator::xds::control_plane::{NodeVisibility, XdsControlPlane};
use joysafeter_orchestrator::xds::delivery::DeliveryRequest;
use joysafeter_orchestrator::xds::inventory::{
    QuarantinedSandbox, RecoveredSandbox, RecoveryDeliveryState, RecoveryInventory,
};
use joysafeter_orchestrator::xds::metrics::xds_health;
use joysafeter_orchestrator::xds::model::DeliveryGeneration;
use joysafeter_orchestrator::xds::model::{ManagedXdsResource, ResourceOwner, ResourceType};
use joysafeter_orchestrator::xds::transport::start_xds_server;
use tokio::net::TcpListener;
use tokio::sync::oneshot;
use tokio_stream::wrappers::{ReceiverStream, TcpListenerStream};
use tonic::transport::Server;
use tonic::Request;

const XDS_TOKEN: &str = "observability-control-plane-token-with-enough-entropy";

fn resource(sandbox_id: SandboxId, name: &str) -> ManagedXdsResource {
    ManagedXdsResource {
        name: name.to_string(),
        resource_type: ResourceType::Listener,
        owner: ResourceOwner::Sandbox(sandbox_id),
        payload: Any {
            type_url: ResourceType::Listener.type_url().to_string(),
            value: b"Bearer sk-secret-resource-payload".to_vec(),
        },
    }
}

fn request(
    node_id: Option<&str>,
    response_nonce: impl Into<String>,
    error_detail: Option<RpcStatus>,
) -> DeltaDiscoveryRequest {
    DeltaDiscoveryRequest {
        node: node_id.map(|id| Node {
            id: id.to_string(),
            ..Default::default()
        }),
        type_url: ResourceType::Listener.type_url().to_string(),
        response_nonce: response_nonce.into(),
        error_detail,
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

async fn start_control_plane() -> (
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
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::NodeScoped);
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

fn unused_local_addr() -> SocketAddr {
    let listener = std::net::TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
        .expect("ephemeral listener must bind");
    let addr = listener.local_addr().expect("listener must have address");
    drop(listener);
    addr
}

async fn wait_for_server(addr: SocketAddr) {
    for _ in 0..50 {
        if tokio::net::TcpStream::connect(addr).await.is_ok() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    panic!("server did not bind {addr}");
}

#[test]
fn xds_health_distinguishes_recovery_from_ready() {
    let recovery = xds_health(AuthorityPhase::RecoveryServing { epoch: 7 });
    assert_eq!(recovery.status_code, 503);
    assert_eq!(recovery.body, "recovery_serving");

    let ready = xds_health(AuthorityPhase::Ready { epoch: 7 });
    assert_eq!(ready.status_code, 200);
    assert_eq!(ready.body, "ready");

    for phase in [
        AuthorityPhase::Standby,
        AuthorityPhase::Staging { epoch: 7 },
        AuthorityPhase::Revoked { epoch: 7 },
    ] {
        assert_eq!(xds_health(phase).status_code, 503);
    }
}

#[tokio::test]
async fn metrics_report_pending_delivery_and_ack_nack_totals() {
    let (control_plane, mut client, shutdown_tx, server, epoch) = start_control_plane().await;
    let (request_tx, request_rx) = tokio::sync::mpsc::channel(8);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open ADS stream")
        .into_inner();
    request_tx
        .send(request(Some("node-a"), "", None))
        .await
        .expect("subscribe LDS");
    next_response(&mut responses, "initial LDS").await;

    let sandbox_id = SandboxId::new();
    control_plane
        .assign_sandbox_node(sandbox_id, "node-a")
        .await
        .expect("assign sandbox node");
    let first = control_plane
        .publish_sandbox_resources(
            DeliveryRequest {
                authority_epoch: epoch,
                sandbox_id,
                generation: DeliveryGeneration {
                    policy_hash: "policy-1".to_string(),
                    policy_version: 1,
                },
            },
            vec![resource(sandbox_id, "listener-a")],
        )
        .await
        .expect("publish first generation")
        .expect("first generation requires delivery");

    let pending = control_plane.metrics_snapshot().await;
    assert_eq!(pending.pending_delivery_count(), 1);
    assert_eq!(pending.active_envoy_node_count(), 1);
    assert_eq!(pending.ownership_transition_total(), 1);
    assert!(pending.oldest_pending_delivery_age() <= Duration::from_secs(1));

    let first_response = next_response(&mut responses, "first LDS update").await;
    request_tx
        .send(request(None, first_response.nonce, None))
        .await
        .expect("ACK first generation");
    control_plane
        .wait_for_delivery(first, Duration::from_secs(1))
        .await
        .expect("first generation ACK");

    let after_ack = control_plane.metrics_snapshot().await;
    assert_eq!(after_ack.pending_delivery_count(), 0);
    assert_eq!(after_ack.ack_total(ResourceType::Listener), 1);
    assert_eq!(after_ack.nack_total(ResourceType::Listener), 0);

    let second = control_plane
        .publish_sandbox_resources(
            DeliveryRequest {
                authority_epoch: epoch,
                sandbox_id,
                generation: DeliveryGeneration {
                    policy_hash: "policy-2".to_string(),
                    policy_version: 2,
                },
            },
            vec![resource(sandbox_id, "listener-b")],
        )
        .await
        .expect("publish second generation")
        .expect("second generation requires delivery");
    let second_response = next_response(&mut responses, "second LDS update").await;
    request_tx
        .send(request(
            None,
            second_response.nonce,
            Some(RpcStatus {
                code: 13,
                message: "Bearer sk-secret-rejection".to_string(),
                details: Vec::new(),
            }),
        ))
        .await
        .expect("NACK second generation");
    assert!(control_plane
        .wait_for_delivery(second, Duration::from_secs(1))
        .await
        .is_err());

    let after_nack = control_plane.metrics_snapshot().await;
    assert_eq!(after_nack.pending_delivery_count(), 0);
    assert_eq!(after_nack.ack_total(ResourceType::Listener), 1);
    assert_eq!(after_nack.nack_total(ResourceType::Listener), 1);

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
async fn metrics_never_render_tokens_resource_payloads_or_dynamic_identity() {
    let authority = XdsAuthority::managed();
    let recovery = authority.begin_staging().expect("begin staging");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::NodeScoped);
    let sandbox_id = SandboxId::new();
    control_plane
        .assign_sandbox_node(sandbox_id, "node-sk-secret")
        .await
        .expect("assign sandbox node");
    control_plane
        .publish_sandbox_resources(
            DeliveryRequest {
                authority_epoch: recovery.epoch(),
                sandbox_id,
                generation: DeliveryGeneration {
                    policy_hash: "Bearer-sk-secret-policy-hash".to_string(),
                    policy_version: 1,
                },
            },
            vec![resource(sandbox_id, "listener-sk-secret")],
        )
        .await
        .expect("publish sensitive fixture")
        .expect("publication requires delivery");

    let rendered = control_plane.metrics_snapshot().await.render_prometheus();
    for forbidden in [
        "Bearer",
        "sk-secret",
        "node-sk-secret",
        "listener-sk-secret",
        &sandbox_id.to_string(),
    ] {
        assert!(
            !rendered.contains(forbidden),
            "metrics leaked forbidden dynamic value: {forbidden}"
        );
    }
    assert!(rendered.contains("joysafeter_xds_authority_phase{phase=\"ready\"} 1"));
    assert!(rendered.contains("joysafeter_xds_pending_deliveries 1"));

    let label_names = rendered
        .lines()
        .filter_map(|line| line.split_once('{').map(|(_, labels)| labels))
        .filter_map(|labels| labels.split_once('}').map(|(labels, _)| labels))
        .flat_map(|labels| labels.split(','))
        .filter_map(|label| label.split_once('=').map(|(name, _)| name))
        .collect::<std::collections::HashSet<_>>();
    assert_eq!(
        label_names,
        std::collections::HashSet::from(["phase", "resource_type", "result", "reason"])
    );
}

#[tokio::test]
async fn metrics_count_authenticated_and_rejected_transport_admission() {
    let authority = XdsAuthority::standalone();
    let recovery = authority.begin_staging().expect("begin staging");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::Unscoped);
    let keyring = XdsAuthKeyring::parse(&format!(r#"{{"active":"{XDS_TOKEN}"}}"#), "active")
        .expect("test keyring");
    let address = unused_local_addr();
    let handle = start_xds_server(
        address,
        control_plane.clone(),
        Arc::new(SharedTokenAuthenticator::new(keyring)),
    )
    .await
    .expect("start authenticated xDS server");
    wait_for_server(address).await;

    let endpoint =
        tonic::transport::Endpoint::from_shared(format!("http://{address}")).expect("xDS endpoint");
    let channel = endpoint
        .connect()
        .await
        .expect("connect unauthenticated client");
    let mut unauthenticated = AggregatedDiscoveryServiceClient::new(channel);
    unauthenticated
        .delta_aggregated_resources(Request::new(tokio_stream::empty()))
        .await
        .expect_err("missing token must be rejected");

    let channel = tonic::transport::Endpoint::from_shared(format!("http://{address}"))
        .expect("xDS endpoint")
        .connect()
        .await
        .expect("connect authenticated client");
    let mut authenticated = AggregatedDiscoveryServiceClient::new(channel);
    let mut request = Request::new(tokio_stream::empty());
    request.metadata_mut().insert(
        "x-joysafeter-xds-token",
        XDS_TOKEN.parse().expect("token metadata"),
    );
    authenticated
        .delta_aggregated_resources(request)
        .await
        .expect("valid token must pass transport admission");

    let snapshot = control_plane.metrics_snapshot().await;
    assert_eq!(snapshot.authenticated_stream_total(), 1);
    assert_eq!(snapshot.rejected_stream_total(), 1);
    assert!(snapshot
        .render_prometheus()
        .contains("joysafeter_xds_rejected_streams_total{reason=\"unauthenticated\"} 1"));
    handle.abort();
}

#[tokio::test]
async fn metrics_classify_invalid_node_identity_without_exposing_it() {
    let (control_plane, mut client, shutdown_tx, server, _epoch) = start_control_plane().await;
    let (request_tx, request_rx) = tokio::sync::mpsc::channel(2);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open ADS stream")
        .into_inner();
    request_tx
        .send(request(None, "", None))
        .await
        .expect("send request without node identity");
    responses
        .message()
        .await
        .expect_err("missing initial node identity must close stream");

    let rendered = control_plane.metrics_snapshot().await.render_prometheus();
    assert!(rendered
        .contains("joysafeter_xds_rejected_streams_total{reason=\"invalid_node_identity\"} 1"));

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
async fn metrics_track_reconnect_cleanup_and_recovery_quarantine() {
    let authority = XdsAuthority::managed();
    let recovery = authority.begin_staging().expect("begin staging");
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::NodeScoped);
    let deferred_id = SandboxId::new();
    let quarantined_id = SandboxId::new();
    let installed = control_plane
        .install_recovery_inventory(
            &recovery,
            RecoveryInventory::new(
                vec![RecoveredSandbox {
                    sandbox_id: deferred_id,
                    generation: DeliveryGeneration {
                        policy_hash: "deferred-policy".to_string(),
                        policy_version: 1,
                    },
                    resources: vec![resource(deferred_id, "deferred-listener")],
                }],
                vec![QuarantinedSandbox {
                    sandbox_id: quarantined_id,
                    reason: "redacted fixture reason".to_string(),
                }],
            )
            .expect("recovery inventory"),
        )
        .await
        .expect("install degraded recovery inventory");
    assert_eq!(
        installed.deliveries[0].state,
        RecoveryDeliveryState::Deferred
    );
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");

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
    let mut client = AggregatedDiscoveryServiceClient::new(channel);
    let (request_tx, request_rx) = tokio::sync::mpsc::channel(2);
    let mut responses = client
        .delta_aggregated_resources(ReceiverStream::new(request_rx))
        .await
        .expect("open ADS stream")
        .into_inner();
    let mut reconnect = request(Some("node-a"), "", None);
    reconnect.initial_resource_versions =
        HashMap::from([("stale-listener-sk-secret".to_string(), "9".to_string())]);
    request_tx
        .send(reconnect)
        .await
        .expect("send reconnect state");
    let response = next_response(&mut responses, "reconnect removal").await;
    assert_eq!(response.removed_resources, vec!["stale-listener-sk-secret"]);

    let snapshot = control_plane.metrics_snapshot().await;
    assert_eq!(snapshot.reconnect_removal_total(), 1);
    assert_eq!(snapshot.degraded_inventory_count(), 2);
    assert!(snapshot
        .render_prometheus()
        .contains("joysafeter_xds_authority_recovery_total{result=\"ready\"} 1"));

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
async fn reconnect_closes_the_superseded_stream_and_counts_the_closure() {
    let (control_plane, mut first_client, shutdown_tx, server, _epoch) =
        start_control_plane().await;
    let mut second_client = first_client.clone();
    let (first_tx, first_rx) = tokio::sync::mpsc::channel(2);
    let mut first_responses = first_client
        .delta_aggregated_resources(ReceiverStream::new(first_rx))
        .await
        .expect("open first ADS stream")
        .into_inner();
    first_tx
        .send(request(Some("node-a"), "", None))
        .await
        .expect("subscribe first stream");
    next_response(&mut first_responses, "first stream snapshot").await;

    let (second_tx, second_rx) = tokio::sync::mpsc::channel(2);
    let mut second_responses = second_client
        .delta_aggregated_resources(ReceiverStream::new(second_rx))
        .await
        .expect("open replacement ADS stream")
        .into_inner();
    second_tx
        .send(request(Some("node-a"), "", None))
        .await
        .expect("subscribe replacement stream");
    next_response(&mut second_responses, "replacement stream snapshot").await;

    let old_stream_result = tokio::time::timeout(Duration::from_secs(1), first_responses.message())
        .await
        .expect("superseded stream must close promptly")
        .expect("superseded stream closure must be graceful");
    assert!(old_stream_result.is_none());
    assert!(control_plane
        .metrics_snapshot()
        .await
        .render_prometheus()
        .contains("joysafeter_xds_stale_session_closures_total 1"));

    drop(first_tx);
    drop(second_tx);
    drop(first_responses);
    drop(second_responses);
    drop(first_client);
    drop(second_client);
    let _ = shutdown_tx.send(());
    server
        .await
        .expect("join ADS server")
        .expect("stop ADS server");
}

#[tokio::test]
async fn metrics_contract_uses_only_aggregate_series() {
    let expected = HashMap::from([
        ("joysafeter_xds_authority_epoch", "gauge"),
        ("joysafeter_xds_active_envoy_nodes", "gauge"),
        ("joysafeter_xds_pending_deliveries", "gauge"),
        ("joysafeter_xds_ack_total", "counter"),
        ("joysafeter_xds_nack_total", "counter"),
        ("joysafeter_xds_reconnect_removals_total", "counter"),
        ("joysafeter_xds_ownership_transitions_total", "counter"),
        ("joysafeter_xds_degraded_inventory", "gauge"),
    ]);
    let authority = XdsAuthority::standalone();
    let rendered = XdsControlPlane::new(authority, NodeVisibility::Unscoped)
        .metrics_snapshot()
        .await
        .render_prometheus();
    for (metric, metric_type) in expected {
        assert!(rendered.contains(metric), "missing metric {metric}");
        assert!(
            rendered.contains(&format!("# TYPE {metric} {metric_type}")),
            "metric {metric} must declare type {metric_type}"
        );
    }
}
