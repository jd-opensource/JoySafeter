use super::*;

#[test]
fn management_authentication_is_exact_and_constant_time_compared() {
    let auth =
        ManagementAuthenticator::new("abcdefghijklmnopqrstuvwxyz012345").expect("valid token");
    let mut headers = HeaderMap::new();
    headers.insert(
        header::AUTHORIZATION,
        "Bearer abcdefghijklmnopqrstuvwxyz012345"
            .parse()
            .expect("header"),
    );
    assert!(auth.authenticate(&headers));
    headers.insert(
        header::AUTHORIZATION,
        "Bearer abcdefghijklmnopqrstuvwxyz012346"
            .parse()
            .expect("header"),
    );
    assert!(!auth.authenticate(&headers));
}

#[test]
fn delivery_timeout_and_envoy_nack_have_distinct_http_statuses() {
    let sandbox_id = SandboxId::new();
    let timeout = application_error(
        GatewayApplicationError::DeliveryTimeout(anyhow::Error::new(
            crate::xds::control_plane::DeliveryWaitError::Timeout { sandbox_id },
        )),
        Some(sandbox_id),
    );
    assert_eq!(timeout.status(), StatusCode::GATEWAY_TIMEOUT);

    let nack = application_error(
        GatewayApplicationError::DeliveryNack(anyhow::Error::new(
            crate::xds::control_plane::DeliveryWaitError::Nacked {
                sandbox_id,
                resource_type: crate::xds::model::ResourceType::Listener,
                reason: "rejected".to_string(),
            },
        )),
        Some(sandbox_id),
    );
    assert_eq!(nack.status(), StatusCode::UNPROCESSABLE_ENTITY);
}
