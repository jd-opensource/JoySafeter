use super::*;

fn keyring() -> XdsAuthKeyring {
    XdsAuthKeyring::parse(r#"{"active":"abcdefghijklmnopqrstuvwxyz012345"}"#, "active")
        .expect("valid test keyring")
}

#[test]
fn listener_addresses_must_not_overlap() {
    let addr = "127.0.0.1:9092".parse().expect("address");
    let error = test_config("gateway-a", addr, addr)
        .validate()
        .expect_err("overlapping listeners must fail");

    assert!(error.to_string().contains("different addresses"));
}

#[test]
fn instance_id_is_required() {
    let error = test_config(
        "  ",
        "127.0.0.1:9092".parse().expect("xds address"),
        "127.0.0.1:9093".parse().expect("http address"),
    )
    .validate()
    .expect_err("empty id must fail");

    assert!(error.to_string().contains("instance id"));
}

#[test]
fn shutdown_grace_must_be_bounded() {
    let mut config = test_config(
        "gateway-a",
        "127.0.0.1:9092".parse().expect("xds address"),
        "127.0.0.1:9093".parse().expect("http address"),
    );
    config.shutdown_grace = Duration::ZERO;

    let error = config.validate().expect_err("zero grace must fail");

    assert!(error.to_string().contains("shutdown grace"));
}

fn management_authenticator() -> ManagementAuthenticator {
    ManagementAuthenticator::new("abcdefghijklmnopqrstuvwxyz012345").expect("management auth")
}

fn test_config(instance_id: &str, xds_addr: SocketAddr, http_addr: SocketAddr) -> GatewayConfig {
    GatewayConfig {
        instance_id: instance_id.to_string(),
        xds_addr,
        http_addr,
        management_grpc_addr: "127.0.0.1:9094".parse().expect("management gRPC address"),
        xds_auth_keyring: keyring(),
        management_authenticator: management_authenticator(),
        management_token: SecretToken("abcdefghijklmnopqrstuvwxyz012345".to_string()),
        leader_election_enabled: false,
        k8s_namespace: "default".to_string(),
        pod_name: None,
        leader_lease_name: "joysafeter-agent-gateway".to_string(),
        leader_identity: "gateway-a".to_string(),
        leader_lease_duration: Duration::from_secs(15),
        leader_renew_interval: Duration::from_secs(5),
        replication_url: None,
        replication_token: None,
        hot_standby_min_acks: DEFAULT_HOT_STANDBY_MIN_ACKS as usize,
        replication_ack_timeout: Duration::from_millis(DEFAULT_REPLICATION_ACK_TIMEOUT_MS),
        node_visibility: NodeVisibility::NodeScoped,
        delivery_timeout: Duration::from_secs(DEFAULT_DELIVERY_TIMEOUT_SECS),
        shutdown_grace: Duration::from_secs(DEFAULT_SHUTDOWN_GRACE_SECS),
        policy_stream_endpoint: None,
    }
}
