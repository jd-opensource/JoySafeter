use super::*;

#[test]
fn config_rejects_redirectable_or_credential_bearing_urls() {
    let token = "a".repeat(32);
    assert!(AgentGatewayClientConfig::new("ftp://gateway.local", token.clone()).is_err());
    assert!(
        AgentGatewayClientConfig::new("https://user:pass@gateway.local", token.clone()).is_err()
    );
    assert!(AgentGatewayClientConfig::new("https://gateway.local?token=x", token).is_err());
}

#[test]
fn debug_output_redacts_management_token() {
    let token = "sensitive-management-token-value-123".to_string();
    let config =
        AgentGatewayClientConfig::new("http://gateway.local", token.clone()).expect("valid config");
    let client = AgentGatewayClient::new(config.clone()).expect("valid client");
    assert!(!format!("{config:?}").contains(&token));
    assert!(!format!("{client:?}").contains(&token));
}

#[test]
fn request_timeout_is_configurable_and_bounded() {
    let token = "a".repeat(32);
    let config = AgentGatewayClientConfig::new("http://gateway.local", token.clone())
        .expect("valid config")
        .with_request_timeout(Duration::from_secs(45))
        .expect("valid timeout");
    assert_eq!(config.request_timeout, Duration::from_secs(45));

    assert!(AgentGatewayClientConfig::new("http://gateway.local", token)
        .expect("valid config")
        .with_request_timeout(Duration::ZERO)
        .is_err());
}

#[test]
fn retries_only_transient_http_statuses() {
    for status in [
        StatusCode::TOO_MANY_REQUESTS,
        StatusCode::SERVICE_UNAVAILABLE,
    ] {
        assert!(retryable_status(status));
    }
    for status in [
        StatusCode::BAD_REQUEST,
        StatusCode::REQUEST_TIMEOUT,
        StatusCode::BAD_GATEWAY,
        StatusCode::GATEWAY_TIMEOUT,
        StatusCode::UNAUTHORIZED,
        StatusCode::CONFLICT,
        StatusCode::INTERNAL_SERVER_ERROR,
    ] {
        assert!(!retryable_status(status));
    }
}

#[tokio::test]
async fn request_timeout_bounds_the_complete_retry_operation() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind test server");
    let address = listener.local_addr().expect("test server address");
    let server = tokio::spawn(async move {
        axum::serve(
            listener,
            axum::Router::new().fallback(|| async { StatusCode::SERVICE_UNAVAILABLE }),
        )
        .await
        .expect("serve transient failures");
    });

    let config = AgentGatewayClientConfig::new(&format!("http://{address}"), "a".repeat(32))
        .expect("valid config")
        .with_request_timeout(Duration::from_millis(80))
        .expect("valid timeout");
    let client = AgentGatewayClient::new(config).expect("client");
    let started = tokio::time::Instant::now();
    let error = client.check_ready().await.expect_err("request times out");

    assert!(error
        .chain()
        .any(|cause| cause.downcast_ref::<AgentGatewayRequestTimeout>().is_some()));
    assert!(
        started.elapsed() < Duration::from_millis(250),
        "retry loop exceeded the total operation deadline: {:?}",
        started.elapsed()
    );
    server.abort();
}
