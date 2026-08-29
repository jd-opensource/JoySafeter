use std::net::{IpAddr, Ipv4Addr, SocketAddr};
use std::sync::Arc;
use std::time::Duration;

use envoy_types::pb::envoy::service::discovery::v3::aggregated_discovery_service_client::AggregatedDiscoveryServiceClient;
use joysafeter_orchestrator::config::{JoySafeterConfig, DEFAULT_XDS_PORT};
use joysafeter_orchestrator::grpc::proto::{OrchestratorMessage, RunnerMessage};
use joysafeter_orchestrator::xds::auth::{
    SharedTokenAuthenticator, XdsAuthKeyring, XdsClientAuthenticator,
};
use joysafeter_orchestrator::xds::authority::XdsAuthority;
use joysafeter_orchestrator::xds::control_plane::{NodeVisibility, XdsControlPlane};
use joysafeter_orchestrator::xds::transport::start_xds_server;
use tonic::codec::ProstCodec;
use tonic::codegen::http::uri::PathAndQuery;
use tonic::transport::Endpoint;
use tonic::{Code, Request};

const ACTIVE_TOKEN: &str = "active-control-plane-token-with-enough-entropy";
const PREVIOUS_TOKEN: &str = "previous-control-plane-token-with-enough-entropy";

fn test_keyring() -> XdsAuthKeyring {
    XdsAuthKeyring::parse(
        &format!(r#"{{"active":"{ACTIVE_TOKEN}","previous":"{PREVIOUS_TOKEN}"}}"#),
        "active",
    )
    .expect("test keyring must parse")
}

fn grpc_xds_config() -> JoySafeterConfig {
    let mut config = JoySafeterConfig::from_env();
    config.envoy_enabled = true;
    config.envoy_xds_mode = "grpc".to_string();
    config.grpc_port = 9090;
    config.xds_port = DEFAULT_XDS_PORT;
    config.xds_auth_keyring = Some(format!(r#"{{"active":"{ACTIVE_TOKEN}"}}"#));
    config.xds_auth_write_key_id = Some("active".to_string());
    config.xds_auth_token = Some(ACTIVE_TOKEN.to_string());
    config
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
fn invalid_or_missing_token_is_rejected_without_echoing_material() {
    let authenticator = SharedTokenAuthenticator::new(test_keyring());

    for token in [None, Some("wrong-control-plane-token")] {
        let error = authenticator
            .authenticate_value(token)
            .expect_err("missing or invalid token must fail closed");
        assert_eq!(error.code(), Code::Unauthenticated);
        assert!(!error.message().contains("wrong-control-plane-token"));
        assert!(!error.message().contains(ACTIVE_TOKEN));
        assert!(!error.message().contains(PREVIOUS_TOKEN));
    }
}

#[test]
fn keyring_accepts_active_and_retained_rotation_tokens() {
    let authenticator = SharedTokenAuthenticator::new(test_keyring());

    let active = authenticator
        .authenticate_value(Some(ACTIVE_TOKEN))
        .expect("active token must authenticate");
    let previous = authenticator
        .authenticate_value(Some(PREVIOUS_TOKEN))
        .expect("retained rotation token must authenticate");

    assert_eq!(active.key_id(), "active");
    assert_eq!(previous.key_id(), "previous");
    assert_eq!(test_keyring().write_token(), ACTIVE_TOKEN);
}

#[test]
fn keyring_rejects_missing_selected_write_key() {
    let error = XdsAuthKeyring::parse(
        r#"{"active":"active-control-plane-token-with-enough-entropy"}"#,
        "missing",
    )
    .expect_err("write key id must select an existing token");

    assert!(!error.to_string().contains(ACTIVE_TOKEN));
}

#[test]
fn keyring_rejects_tokens_unsafe_for_envoy_bootstrap_metadata() {
    let error = XdsAuthKeyring::parse(
        r#"{"active":"token-with-a-quote-\"-and-enough-padding"}"#,
        "active",
    )
    .expect_err("bootstrap metadata tokens must use a shell-safe alphabet");

    assert!(error.to_string().contains("URL-safe"));
    assert!(!error.to_string().contains("token-with-a-quote"));
}

#[test]
fn grpc_xds_requires_authentication_configuration() {
    let mut config = grpc_xds_config();
    config.xds_auth_keyring = None;
    assert!(config
        .validate()
        .expect_err("gRPC xDS must require a keyring")
        .to_string()
        .contains("JOYSAFETER_XDS_AUTH_KEYRING"));

    config.xds_auth_keyring = Some(format!(r#"{{"active":"{ACTIVE_TOKEN}"}}"#));
    config.xds_auth_write_key_id = None;
    assert!(config
        .validate()
        .expect_err("gRPC xDS must require a write key id")
        .to_string()
        .contains("JOYSAFETER_XDS_AUTH_WRITE_KEY_ID"));

    config.xds_auth_write_key_id = Some("active".to_string());
    config.xds_auth_token = None;
    assert!(config
        .validate()
        .expect_err("Envoy must receive the selected write token")
        .to_string()
        .contains("JOYSAFETER_XDS_AUTH_TOKEN"));
}

#[test]
fn configured_envoy_token_must_match_selected_write_key() {
    let mut config = grpc_xds_config();
    config.xds_auth_token = Some("different-control-plane-token-value".to_string());

    let error = config
        .validate()
        .expect_err("Envoy token drift must fail startup validation");
    assert!(error.to_string().contains("must match"));
    assert!(!error.to_string().contains(ACTIVE_TOKEN));
    assert!(!error
        .to_string()
        .contains("different-control-plane-token-value"));
}

#[test]
fn runner_and_xds_ports_must_be_distinct() {
    let mut config = grpc_xds_config();
    config.xds_port = config.grpc_port;

    let error = config
        .validate()
        .expect_err("runner and xDS must never share a port");
    assert!(error.to_string().contains("must use different ports"));
}

#[test]
fn xds_port_has_a_dedicated_default() {
    assert_eq!(DEFAULT_XDS_PORT, 9092);
    assert_ne!(DEFAULT_XDS_PORT, 9090);
}

#[tokio::test]
async fn xds_endpoint_rejects_unauthenticated_ads_and_exposes_no_agent_bridge() {
    let addr = unused_local_addr();
    let authenticator: Arc<dyn XdsClientAuthenticator> =
        Arc::new(SharedTokenAuthenticator::new(test_keyring()));
    let handle = start_xds_server(
        addr,
        XdsControlPlane::new(XdsAuthority::standalone(), NodeVisibility::Unscoped),
        authenticator,
    )
    .await
    .expect("xDS server must start");
    wait_for_server(addr).await;

    let endpoint = format!("http://{addr}");
    let ads_channel = Endpoint::from_shared(endpoint.clone())
        .expect("ADS endpoint URI must be valid")
        .connect()
        .await
        .expect("ADS client must connect");
    let mut ads = AggregatedDiscoveryServiceClient::new(ads_channel);
    let error = ads
        .delta_aggregated_resources(Request::new(tokio_stream::empty()))
        .await
        .expect_err("missing token must be rejected before stream admission");
    assert_eq!(error.code(), Code::Unauthenticated);

    let channel = Endpoint::from_shared(endpoint)
        .expect("runner endpoint URI must be valid")
        .connect()
        .await
        .expect("runner client must connect to inspect route isolation");
    let mut runner = tonic::client::Grpc::new(channel);
    runner
        .ready()
        .await
        .expect("runner route probe client must become ready");
    let error = runner
        .streaming(
            Request::new(tokio_stream::empty::<RunnerMessage>()),
            PathAndQuery::from_static("/joysafeter.AgentBridge/Session"),
            ProstCodec::<RunnerMessage, OrchestratorMessage>::default(),
        )
        .await
        .expect_err("AgentBridge must not be registered on the xDS endpoint");
    assert_eq!(error.code(), Code::Unimplemented);

    handle.abort();
}

#[test]
fn runner_transport_source_does_not_register_ads() {
    let source = include_str!("../src/grpc/server.rs");
    assert!(!source.contains("AggregatedDiscoveryServiceServer"));
    assert!(!source.contains("xds_service:"));
}

#[test]
fn xds_bind_address_uses_dedicated_host_and_port() {
    let mut config = grpc_xds_config();
    config.xds_host = "127.0.0.1".to_string();
    config.xds_port = 19092;

    assert_eq!(
        config.xds_addr(),
        SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 19092)
    );
}
