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

#[test]
fn policy_stream_concurrency_cannot_exceed_admission_capacity() {
    let mut config = test_config(
        "gateway-a",
        "127.0.0.1:9092".parse().expect("xds address"),
        "127.0.0.1:9093".parse().expect("http address"),
    );
    config.policy_stream_max_outstanding = 8;
    config.policy_stream_max_concurrency = 9;

    let error = config.validate().expect_err("invalid stream limits");
    assert!(error.to_string().contains("policy stream limits"));
}

#[test]
fn replication_transport_timings_are_bounded() {
    let mut config = test_config(
        "gateway-a",
        "127.0.0.1:9092".parse().expect("xds address"),
        "127.0.0.1:9093".parse().expect("http address"),
    );
    config.replication_keepalive_timeout = Duration::from_secs(11);
    config.replication_keepalive_interval = Duration::from_secs(10);

    let error = config.validate().expect_err("invalid keepalive");
    assert!(error.to_string().contains("keepalive"));
}

#[test]
fn dns_cache_max_hosts_must_be_positive() {
    let mut config = test_config(
        "gateway-a",
        "127.0.0.1:9092".parse().expect("xds address"),
        "127.0.0.1:9093".parse().expect("http address"),
    );
    config.dns_cache_max_hosts = 0;

    let error = config
        .validate()
        .expect_err("zero DNS cache capacity must fail");
    assert!(error.to_string().contains("DNS cache max hosts"));
}

fn test_config(instance_id: &str, xds_addr: SocketAddr, http_addr: SocketAddr) -> GatewayConfig {
    GatewayConfig {
        instance_id: instance_id.to_string(),
        xds_addr,
        http_addr,
        management_grpc_addr: "127.0.0.1:9094".parse().expect("management gRPC address"),
        xds_auth_keyring: keyring(),
        management_token: SecretToken("abcdefghijklmnopqrstuvwxyz012345".to_string()),
        leader_election_enabled: false,
        k8s_namespace: "default".to_string(),
        pod_name: None,
        leader_lease_name: "joysafeter-agent-gateway".to_string(),
        leader_identity: "gateway-a".to_string(),
        leader_lease_duration: Duration::from_secs(15),
        leader_renew_interval: Duration::from_secs(5),
        replication_endpoint: None,
        replication_token: None,
        hot_standby_min_acks: DEFAULT_HOT_STANDBY_MIN_ACKS as usize,
        replication_ack_timeout: Duration::from_millis(DEFAULT_REPLICATION_ACK_TIMEOUT_MS),
        policy_stream_max_outstanding: DEFAULT_POLICY_STREAM_MAX_OUTSTANDING,
        policy_stream_max_concurrency: DEFAULT_POLICY_STREAM_MAX_CONCURRENCY,
        policy_lane_queue_capacity: DEFAULT_POLICY_LANE_QUEUE_CAPACITY,
        max_policy_streams: DEFAULT_MAX_POLICY_STREAMS,
        max_replication_streams: DEFAULT_MAX_REPLICATION_STREAMS,
        replication_reconnect_base_delay: Duration::from_millis(
            DEFAULT_REPLICATION_RECONNECT_BASE_DELAY_MS,
        ),
        replication_reconnect_max_delay: Duration::from_millis(
            DEFAULT_REPLICATION_RECONNECT_MAX_DELAY_MS,
        ),
        replication_keepalive_interval: Duration::from_secs(
            DEFAULT_REPLICATION_KEEPALIVE_INTERVAL_SECS,
        ),
        replication_keepalive_timeout: Duration::from_secs(
            DEFAULT_REPLICATION_KEEPALIVE_TIMEOUT_SECS,
        ),
        node_visibility: NodeVisibility::NodeScoped,
        delivery_timeout: Duration::from_secs(DEFAULT_DELIVERY_TIMEOUT_SECS),
        dns_cache_max_hosts: DEFAULT_DNS_CACHE_MAX_HOSTS,
        shutdown_grace: Duration::from_secs(DEFAULT_SHUTDOWN_GRACE_SECS),
    }
}
