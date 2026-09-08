use joysafeter_agent_gateway_contract::ApplySandboxPolicyRequest;
use tonic::Code;

use super::*;

#[test]
fn internal_error_details_are_not_exposed_to_grpc_clients() {
    let status = app_error_to_status(&GatewayApplicationError::Infrastructure(anyhow::anyhow!(
        "database password=do-not-leak"
    )));

    assert_eq!(status.code(), Code::Unavailable);
    assert_eq!(
        status.message(),
        "Gateway infrastructure is temporarily unavailable"
    );
    assert!(!status.message().contains("do-not-leak"));
    assert_eq!(
        status
            .metadata()
            .get(ERROR_REASON_METADATA)
            .and_then(|value| value.to_str().ok()),
        Some("infrastructure_unavailable")
    );
    assert_eq!(
        status
            .metadata()
            .get(ERROR_RETRYABLE_METADATA)
            .and_then(|value| value.to_str().ok()),
        Some("true")
    );
}

#[test]
fn terminal_errors_have_stable_reason_and_retryability_metadata() {
    let status = app_error_to_status(&GatewayApplicationError::InvalidPolicy(
        "header contained a secret value".to_string(),
    ));

    assert_eq!(status.code(), Code::InvalidArgument);
    assert_eq!(status.message(), "policy validation failed");
    assert!(!status.message().contains("secret value"));
    assert_eq!(
        status
            .metadata()
            .get(ERROR_REASON_METADATA)
            .and_then(|value| value.to_str().ok()),
        Some("invalid_policy")
    );
    assert_eq!(
        status
            .metadata()
            .get(ERROR_RETRYABLE_METADATA)
            .and_then(|value| value.to_str().ok()),
        Some("false")
    );
}

#[test]
fn stream_errors_preserve_command_correlation_without_internal_details() {
    let command_id = uuid::Uuid::now_v7().to_string();
    let response = stream_application_error(
        command_id.clone(),
        &GatewayApplicationError::DeliveryNack(anyhow::anyhow!(
            "upstream header secret=do-not-leak"
        )),
    );

    assert_eq!(response.command_id, command_id);
    assert!(!response.success);
    assert_eq!(response.error_code, "policy_nacked");
    assert!(!response.retryable);
    assert_eq!(response.error_message, "Envoy rejected the policy change");
    assert!(!response.error_message.contains("do-not-leak"));
}

#[test]
fn protobuf_generation_rejects_zero_and_overflow() {
    assert!(checked_proto_generation(ProtoPolicyGeneration {
        policy_hash: "a".repeat(64),
        policy_version: 0,
    })
    .is_none());
    assert!(checked_proto_generation(ProtoPolicyGeneration {
        policy_hash: "a".repeat(64),
        policy_version: i64::MAX as u64 + 1,
    })
    .is_none());
}

#[tokio::test]
async fn commands_for_one_sandbox_complete_in_receive_order() {
    use crate::application::policy_publisher::PolicyPublisher;
    use crate::application::{GatewayRuntimeConfig, PolicyProjectionRegistry};
    use crate::xds::control_plane::{NodeVisibility, XdsControlPlane};
    use std::time::Duration;

    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    let application = GatewayApplication::new(
        authority,
        PolicyPublisher::new(control_plane.clone()),
        control_plane,
        PolicyProjectionRegistry::default(),
        GatewayRuntimeConfig {
            delivery_timeout: Duration::from_millis(10),
            node_assignment_timeout: Duration::from_millis(10),
        },
    );
    let dispatcher = PolicyCommandDispatcher::new(application);
    let sandbox_id = SandboxId::new();
    let (response_tx, mut response_rx) = mpsc::channel(2);

    let command_ids = [
        uuid::Uuid::now_v7().to_string(),
        uuid::Uuid::now_v7().to_string(),
    ];
    for command_id in &command_ids {
        let generation = joysafeter_agent_gateway_contract::PolicyGeneration {
            policy_hash: "a".repeat(64),
            policy_version: 1,
        };
        dispatcher
            .dispatch(
                PolicyStreamRequest {
                    command_id: command_id.clone(),
                    command: Some(policy_stream_request::Command::ApplyPolicy(
                        StreamApplyPolicy {
                            sandbox_id: sandbox_id.to_string(),
                            policy: Some(
                                crate::adapters::proto_conversion::policy_to_proto(
                                    ApplySandboxPolicyRequest {
                                        generation,
                                        allowlist_hosts: Vec::new(),
                                        credential_routes: Vec::new(),
                                        proxy_auth_token: None,
                                    },
                                )
                                .expect("convert request"),
                            ),
                        },
                    )),
                },
                response_tx.clone(),
            )
            .await;
    }

    let first = response_rx
        .recv()
        .await
        .expect("first response")
        .expect("ok");
    let second = response_rx
        .recv()
        .await
        .expect("second response")
        .expect("ok");
    assert_eq!(first.command_id, command_ids[0]);
    assert_eq!(second.command_id, command_ids[1]);
}

#[tokio::test]
async fn saturated_dispatcher_fails_fast_instead_of_queueing_without_bound() {
    use crate::application::policy_publisher::PolicyPublisher;
    use crate::application::{GatewayRuntimeConfig, PolicyProjectionRegistry};
    use crate::xds::control_plane::{NodeVisibility, XdsControlPlane};
    use std::time::Duration;

    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    let dispatcher = PolicyCommandDispatcher::new(GatewayApplication::new(
        authority,
        PolicyPublisher::new(control_plane.clone()),
        control_plane,
        PolicyProjectionRegistry::default(),
        GatewayRuntimeConfig {
            delivery_timeout: Duration::from_millis(10),
            node_assignment_timeout: Duration::from_millis(10),
        },
    ));
    let _all_permits = dispatcher
        .admission_permits
        .clone()
        .acquire_many_owned(MAX_OUTSTANDING_POLICY_COMMANDS as u32)
        .await
        .expect("reserve capacity");
    let command_id = uuid::Uuid::now_v7().to_string();
    let (response_tx, mut response_rx) = mpsc::channel(1);

    tokio::time::timeout(
        Duration::from_millis(20),
        dispatcher.dispatch(
            PolicyStreamRequest {
                command_id: command_id.clone(),
                command: Some(policy_stream_request::Command::ApplyPolicy(
                    StreamApplyPolicy {
                        sandbox_id: SandboxId::new().to_string(),
                        policy: None,
                    },
                )),
            },
            response_tx,
        ),
    )
    .await
    .expect("overload response must not wait");

    let response = response_rx
        .recv()
        .await
        .expect("overload response")
        .expect("stream response");
    assert_eq!(response.command_id, command_id);
    assert_eq!(response.error_code, "gateway_overloaded");
    assert!(response.retryable);
}

#[tokio::test]
async fn policy_stream_authentication_rejects_missing_and_wrong_tokens() {
    use crate::application::policy_publisher::PolicyPublisher;
    use crate::application::{GatewayRuntimeConfig, PolicyProjectionRegistry};
    use crate::xds::control_plane::{NodeVisibility, XdsControlPlane};
    use std::time::Duration;

    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    let application = GatewayApplication::new(
        authority.clone(),
        PolicyPublisher::new(control_plane.clone()),
        control_plane,
        PolicyProjectionRegistry::default(),
        GatewayRuntimeConfig {
            delivery_timeout: Duration::from_millis(10),
            node_assignment_timeout: Duration::from_millis(10),
        },
    );
    let server = GatewayManagementServer::new(
        application,
        &"a".repeat(32),
        "gateway-a".to_string(),
        "boot-a".to_string(),
        authority,
    )
    .expect("server");

    assert_eq!(
        server
            .authenticate(&Request::new(()))
            .expect_err("missing token")
            .code(),
        Code::Unauthenticated
    );
    let mut wrong = Request::new(());
    wrong.metadata_mut().insert(
        "authorization",
        "Bearer bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
            .parse()
            .expect("metadata"),
    );
    assert_eq!(
        server.authenticate(&wrong).expect_err("wrong token").code(),
        Code::Unauthenticated
    );
}
