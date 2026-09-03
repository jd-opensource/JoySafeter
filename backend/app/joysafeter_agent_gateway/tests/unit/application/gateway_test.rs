use super::{GatewayApplication, GatewayApplicationError};
use crate::application::policy_publisher::PolicyPublisher;
use crate::application::{GatewayRuntimeConfig, PolicyProjectionRegistry};
use crate::ids::SandboxId;
use crate::xds::authority::{AuthorityPhase, XdsAuthority};
use crate::xds::control_plane::{NodeVisibility, XdsControlPlane};
use crate::xds::inventory::RecoveryInventory;
use joysafeter_agent_gateway_contract::{
    AppliedSandboxGeneration, ApplySandboxPolicyRequest, PolicyGeneration, SandboxPlacement,
};
use std::time::Duration;

fn build_app(delivery_timeout: Duration) -> (GatewayApplication, XdsAuthority, XdsControlPlane) {
    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    let projections = PolicyProjectionRegistry::default();
    let publisher = PolicyPublisher::new(control_plane.clone());
    let app = GatewayApplication::new(
        authority.clone(),
        publisher,
        control_plane.clone(),
        projections,
        GatewayRuntimeConfig {
            delivery_timeout,
            node_assignment_timeout: delivery_timeout,
        },
    );
    (app, authority, control_plane)
}

/// A node-scoped application (delivery targets a specific Envoy node), used to
/// exercise the bounded owner-node wait when no placement has arrived.
fn build_node_scoped_app(
    delivery_timeout: Duration,
    node_assignment_timeout: Duration,
) -> (GatewayApplication, XdsAuthority, XdsControlPlane) {
    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::NodeScoped);
    let projections = PolicyProjectionRegistry::default();
    let publisher = PolicyPublisher::new(control_plane.clone());
    let app = GatewayApplication::new(
        authority.clone(),
        publisher,
        control_plane.clone(),
        projections,
        GatewayRuntimeConfig {
            delivery_timeout,
            node_assignment_timeout,
        },
    );
    (app, authority, control_plane)
}

/// Drive the authority (and its control plane) to a serving `Ready` state at
/// epoch 1 with an empty recovered inventory.
async fn drive_to_ready(authority: &XdsAuthority, control_plane: &XdsControlPlane) {
    let recovery = authority.begin_staging().expect("begin staging");
    control_plane
        .install_recovery_inventory(
            &recovery,
            RecoveryInventory::new(Vec::new()).expect("empty inventory"),
        )
        .await
        .expect("install inventory");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");
}

fn valid_request() -> ApplySandboxPolicyRequest {
    ApplySandboxPolicyRequest {
        generation: PolicyGeneration {
            policy_hash: "a".repeat(64),
            policy_version: 1,
        },
        allowlist_hosts: vec!["api.openai.com".to_string()],
        credential_routes: Vec::new(),
        proxy_auth_token: None,
    }
}

#[tokio::test]
async fn apply_policy_rejects_an_invalid_policy_before_touching_the_authority() {
    let (app, _authority, _control_plane) = build_app(Duration::from_millis(50));
    let mut request = valid_request();
    request.generation.policy_hash = "not-a-sha256".to_string();
    let error = app
        .apply_policy(SandboxId::new(), request)
        .await
        .unwrap_err();
    assert!(matches!(error, GatewayApplicationError::InvalidPolicy(_)));
}

#[tokio::test]
async fn mutations_require_a_serving_authority() {
    // Authority left in Standby: no mutation guard is available.
    let (app, _authority, _control_plane) = build_app(Duration::from_millis(50));

    assert!(matches!(
        app.remove_policy(
            SandboxId::new(),
            PolicyGeneration {
                policy_hash: "a".repeat(64),
                policy_version: 1,
            },
        )
        .await
        .unwrap_err(),
        GatewayApplicationError::AuthorityUnavailable
    ));
    assert!(matches!(
        app.assign_placement(SandboxId::new(), "node-a".to_string())
            .await
            .unwrap_err(),
        GatewayApplicationError::AuthorityUnavailable
    ));
    assert!(matches!(
        app.apply_policy(SandboxId::new(), valid_request())
            .await
            .unwrap_err(),
        GatewayApplicationError::AuthorityUnavailable
    ));
}

#[tokio::test]
async fn apply_policy_rolls_back_the_projection_when_delivery_times_out() {
    // No Envoy is connected, so the delivery wait must time out and the
    // staged projection must be rolled back rather than committed.
    let (app, authority, control_plane) = build_app(Duration::from_millis(50));
    drive_to_ready(&authority, &control_plane).await;

    let sandbox_id = SandboxId::new();
    let error = app
        .apply_policy(sandbox_id, valid_request())
        .await
        .unwrap_err();
    assert!(matches!(error, GatewayApplicationError::DeliveryTimeout(_)));

    // Nothing was committed to the projection inventory.
    assert!(app.projections().inventory().is_empty());
}

#[tokio::test]
async fn complete_recovery_rejects_a_mismatched_epoch() {
    let (app, authority, control_plane) = build_app(Duration::from_millis(50));
    drive_to_ready(&authority, &control_plane).await; // Ready { epoch: 1 }

    let error = app.complete_recovery(2, Vec::new()).await.unwrap_err();
    assert!(matches!(error, GatewayApplicationError::AuthorityChanged));
}

#[tokio::test]
async fn complete_recovery_rejects_a_projection_mismatch() {
    let (app, authority, control_plane) = build_app(Duration::from_millis(50));
    let recovery = authority.begin_staging().expect("begin staging");
    control_plane
        .install_recovery_inventory(
            &recovery,
            RecoveryInventory::new(Vec::new()).expect("empty inventory"),
        )
        .await
        .expect("install inventory");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");

    // The projection is empty, but the Orchestrator claims a sandbox exists.
    let expected = vec![AppliedSandboxGeneration {
        sandbox_id: SandboxId::new().to_string(),
        generation: PolicyGeneration {
            policy_hash: "a".repeat(64),
            policy_version: 1,
        },
    }];
    let error = app.complete_recovery(1, expected).await.unwrap_err();
    assert!(matches!(error, GatewayApplicationError::RecoveryMismatch));
    // The authority stays out of Ready so it does not start serving stale state.
    assert_eq!(
        authority.phase(),
        AuthorityPhase::RecoveryServing { epoch: 1 }
    );
}

#[tokio::test]
async fn complete_recovery_marks_ready_when_the_projection_matches() {
    let (app, authority, control_plane) = build_app(Duration::from_millis(50));
    let recovery = authority.begin_staging().expect("begin staging");
    control_plane
        .install_recovery_inventory(
            &recovery,
            RecoveryInventory::new(Vec::new()).expect("empty inventory"),
        )
        .await
        .expect("install inventory");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");

    app.complete_recovery(1, Vec::new())
        .await
        .expect("recovery completes");
    assert_eq!(authority.phase(), AuthorityPhase::Ready { epoch: 1 });
}

#[tokio::test]
async fn assign_placement_rejects_an_invalid_node_id() {
    let (app, _authority, _control_plane) = build_app(Duration::from_millis(50));
    let error = app
        .assign_placement(SandboxId::new(), "   ".to_string())
        .await
        .unwrap_err();
    assert!(matches!(
        error,
        GatewayApplicationError::InvalidPlacement(_)
    ));
}

#[tokio::test]
async fn reconcile_placements_rejects_duplicate_and_invalid_sandbox_ids() {
    let (app, _authority, _control_plane) = build_app(Duration::from_millis(50));

    let duplicated = SandboxId::new().to_string();
    let duplicate = vec![
        SandboxPlacement {
            sandbox_id: duplicated.clone(),
            node_id: "node-a".to_string(),
        },
        SandboxPlacement {
            sandbox_id: duplicated,
            node_id: "node-b".to_string(),
        },
    ];
    assert!(matches!(
        app.reconcile_placements(duplicate).await.unwrap_err(),
        GatewayApplicationError::InvalidPlacement(_)
    ));

    let invalid = vec![SandboxPlacement {
        sandbox_id: "not-a-uuid".to_string(),
        node_id: "node-a".to_string(),
    }];
    assert!(matches!(
        app.reconcile_placements(invalid).await.unwrap_err(),
        GatewayApplicationError::InvalidPlacement(_)
    ));
}

#[tokio::test]
async fn prune_policies_rejects_an_invalid_inventory() {
    let (app, _authority, _control_plane) = build_app(Duration::from_millis(50));
    let error = app
        .prune_policies(vec!["not-a-uuid".to_string()])
        .await
        .unwrap_err();
    assert!(matches!(
        error,
        GatewayApplicationError::InvalidInventory(_)
    ));
}

#[tokio::test]
async fn prune_policies_returns_nothing_when_no_sandboxes_are_configured() {
    let (app, authority, control_plane) = build_app(Duration::from_millis(50));
    drive_to_ready(&authority, &control_plane).await;

    let stale = app.prune_policies(Vec::new()).await.expect("prune");
    assert!(stale.is_empty());
}

#[tokio::test]
async fn placement_operations_succeed_against_a_serving_authority() {
    let (app, authority, control_plane) = build_app(Duration::from_millis(50));
    drive_to_ready(&authority, &control_plane).await;

    app.assign_placement(SandboxId::new(), "node-a".to_string())
        .await
        .expect("assign placement");
    app.remove_placement(SandboxId::new())
        .await
        .expect("remove placement");
    app.reconcile_placements(vec![SandboxPlacement {
        sandbox_id: SandboxId::new().to_string(),
        node_id: "node-a".to_string(),
    }])
    .await
    .expect("reconcile placements");
}

#[tokio::test]
async fn apply_policy_is_node_not_ready_without_blocking_when_unplaced() {
    // Node-scoped sandbox with no Envoy node assignment: the pre-lock owner-node
    // wait is bounded and returns NodeNotReady instead of hanging (and holding
    // the shared mutation lock) until a placement eventually arrives.
    let (app, authority, control_plane) =
        build_node_scoped_app(Duration::from_secs(30), Duration::from_millis(100));
    drive_to_ready(&authority, &control_plane).await;

    let started = tokio::time::Instant::now();
    let error = app
        .apply_policy(SandboxId::new(), valid_request())
        .await
        .expect_err("apply must not succeed without a node assignment");

    assert!(matches!(error, GatewayApplicationError::NodeNotReady));
    // Bounded by node_assignment_timeout (100ms), NOT by delivery_timeout (30s).
    assert!(
        started.elapsed() < Duration::from_secs(2),
        "apply blocked for {:?}; owner-node wait is not bounded",
        started.elapsed()
    );
}

#[tokio::test]
async fn placement_can_unblock_an_apply_waiting_for_the_same_sandbox() {
    let (app, authority, control_plane) =
        build_node_scoped_app(Duration::from_millis(100), Duration::from_millis(500));
    drive_to_ready(&authority, &control_plane).await;

    let sandbox_id = SandboxId::new();
    let apply = {
        let app = app.clone();
        tokio::spawn(async move { app.apply_policy(sandbox_id, valid_request()).await })
    };
    tokio::time::sleep(Duration::from_millis(25)).await;
    tokio::time::timeout(
        Duration::from_millis(150),
        app.assign_placement(sandbox_id, "node-a".to_string()),
    )
    .await
    .expect("placement must not be blocked by its policy's owner-node wait")
    .expect("placement succeeds");

    assert!(matches!(
        apply.await.expect("apply task"),
        Err(GatewayApplicationError::DeliveryTimeout(_))
    ));
}

#[tokio::test]
async fn one_sandbox_delivery_wait_does_not_block_another_sandbox_mutation() {
    let delivery_timeout = Duration::from_millis(400);
    let (app, authority, control_plane) = build_app(delivery_timeout);
    drive_to_ready(&authority, &control_plane).await;

    let blocked_sandbox = SandboxId::new();
    let other_sandbox = SandboxId::new();
    let blocked_apply = {
        let app = app.clone();
        tokio::spawn(async move { app.apply_policy(blocked_sandbox, valid_request()).await })
    };
    tokio::time::sleep(Duration::from_millis(30)).await;

    tokio::time::timeout(
        Duration::from_millis(150),
        app.assign_placement(other_sandbox, "node-b".to_string()),
    )
    .await
    .expect("an unrelated sandbox must not queue behind the Envoy ACK wait")
    .expect("placement succeeds");

    assert!(matches!(
        blocked_apply.await.expect("apply task"),
        Err(GatewayApplicationError::DeliveryTimeout(_))
    ));
}

#[tokio::test]
async fn cancelled_caller_does_not_cancel_started_policy_cleanup() {
    let delivery_timeout = Duration::from_millis(100);
    let (app, authority, control_plane) = build_app(delivery_timeout);
    drive_to_ready(&authority, &control_plane).await;

    let sandbox_id = SandboxId::new();
    let caller = {
        let app = app.clone();
        tokio::spawn(async move { app.apply_policy(sandbox_id, valid_request()).await })
    };
    tokio::time::sleep(Duration::from_millis(25)).await;
    caller.abort();

    tokio::time::sleep(delivery_timeout + Duration::from_millis(100)).await;
    assert!(
        !app.projections().contains_state(sandbox_id),
        "the detached mutation must roll back its staged projection after timeout"
    );
}
