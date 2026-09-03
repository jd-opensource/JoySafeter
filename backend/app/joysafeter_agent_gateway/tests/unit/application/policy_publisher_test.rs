use super::*;

use crate::domain::egress_policy::{
    EgressCredentialRoute, EgressExposure, EgressKind, EgressPathMapping, EgressPathMatcher,
    EgressRetryMode, SandboxCredentials,
};
use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::NodeVisibility;

#[tokio::test]
async fn publishes_one_atomic_sandbox_resource_bundle() {
    let authority = XdsAuthority::standalone();
    let recovery = authority.begin_staging().expect("begin recovery");
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    control_plane
        .install_recovery_inventory(
            &recovery,
            crate::xds::inventory::RecoveryInventory::new(Vec::new()).expect("empty inventory"),
        )
        .await
        .expect("install inventory");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");

    let sandbox_id = SandboxId::new();
    let publisher = PolicyPublisher::new(control_plane.clone());
    let policy =
        SandboxCredentials::default().to_policy(&sandbox_id, vec!["api.openai.com".to_string()]);
    let generation = DeliveryGeneration {
        policy_hash: "policy-hash-1".to_string(),
        policy_version: 1,
    };
    let outcome = publisher
        .publish(
            authority.phase().epoch().expect("authority epoch"),
            sandbox_id,
            generation,
            policy,
        )
        .await
        .expect("publish policy");

    assert!(matches!(outcome, PublishOutcome::Awaiting(_)));
    assert!(control_plane
        .configured_sandbox_ids(ResourceType::Listener)
        .await
        .contains(&sandbox_id));
}

#[tokio::test]
async fn embeds_resolved_credentials_during_publication() {
    let authority = XdsAuthority::standalone();
    let recovery = authority.begin_staging().expect("begin recovery");
    let control_plane = XdsControlPlane::new(authority.clone(), NodeVisibility::Unscoped);
    control_plane
        .install_recovery_inventory(
            &recovery,
            crate::xds::inventory::RecoveryInventory::new(Vec::new()).expect("empty inventory"),
        )
        .await
        .expect("install inventory");
    authority
        .begin_recovery_serving(&recovery)
        .expect("begin recovery serving");
    authority.mark_ready(&recovery).expect("mark ready");

    let sandbox_id = SandboxId::new();
    let publisher = PolicyPublisher::new(control_plane.clone());
    let policy = SandboxCredentials {
        routes: vec![EgressCredentialRoute {
            id: "llm".to_string(),
            kind: EgressKind::Llm,
            exposure: EgressExposure::Placeholder,
            match_host: "llm-egress.internal".to_string(),
            path_mapping: EgressPathMapping::Passthrough {
                matcher: EgressPathMatcher::Any,
            },
            retry_mode: EgressRetryMode::Disabled,
            upstream_host: "api.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            cluster_name: String::new(),
            vetted_addresses: Vec::new(),
            inject_headers: vec![(
                "authorization".to_string(),
                "Bearer direct-xds-secret".to_string(),
            )],
            remove_headers: vec![
                "x-api-key".to_string(),
                "api-key".to_string(),
                "x-goog-api-key".to_string(),
                "proxy-authorization".to_string(),
            ],
        }],
        proxy_auth_token: None,
    }
    .to_policy(&sandbox_id, Vec::new());
    publisher
        .publish(
            authority.phase().epoch().expect("authority epoch"),
            sandbox_id,
            DeliveryGeneration {
                policy_hash: "a".repeat(64),
                policy_version: 7,
            },
            policy,
        )
        .await
        .expect("publish policy");

    let listener = control_plane
        .snapshot_resources(ResourceType::Listener)
        .await
        .into_iter()
        .next()
        .expect("listener");
    let secret = "Bearer direct-xds-secret";
    assert!(listener
        .payload
        .value
        .windows(secret.len())
        .any(|window| window == secret.as_bytes()));
}
