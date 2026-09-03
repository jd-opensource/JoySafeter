use super::*;

use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, CredentialRoute, EgressExposure, EgressKind, PathMapping,
    PolicyGeneration, ResolvedHeader, RetryMode, SandboxPlacement,
};

use crate::xds::authority::XdsAuthority;
use crate::xds::control_plane::NodeVisibility;

fn projector() -> ReplicaProjector {
    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::Unscoped);
    let projections = PolicyProjectionRegistry::default();
    let publisher = PolicyPublisher::new(control_plane.clone());
    ReplicaProjector::new(
        control_plane,
        publisher,
        projections,
        Arc::new(Mutex::new(())),
    )
}

fn replicated_policy(sandbox_id: &SandboxId, version: i64) -> ReplicatedPolicy {
    ReplicatedPolicy {
        sandbox_id: sandbox_id.to_string(),
        policy: ApplySandboxPolicyRequest {
            generation: PolicyGeneration {
                policy_hash: format!("{version:064x}"),
                policy_version: version,
            },
            allowlist_hosts: vec!["api.openai.com".to_string()],
            credential_routes: Vec::new(),
            proxy_auth_token: None,
        },
    }
}

#[test]
fn validate_node_rejects_empty_and_oversized_ids() {
    assert!(validate_node(" ").is_err());
    assert!(validate_node(&"n".repeat(254)).is_err());
    assert!(validate_node("node-a").is_ok());
}

#[test]
fn parse_assignments_maps_distinct_placements() {
    let a = SandboxId::new().to_string();
    let b = SandboxId::new().to_string();
    let assignments = parse_assignments(&[
        SandboxPlacement {
            sandbox_id: a,
            node_id: "node-a".to_string(),
        },
        SandboxPlacement {
            sandbox_id: b,
            node_id: "node-b".to_string(),
        },
    ])
    .expect("assignments");
    assert_eq!(assignments.len(), 2);
}

#[test]
fn parse_assignments_rejects_a_duplicate_sandbox() {
    let id = SandboxId::new().to_string();
    let result = parse_assignments(&[
        SandboxPlacement {
            sandbox_id: id.clone(),
            node_id: "node-a".to_string(),
        },
        SandboxPlacement {
            sandbox_id: id,
            node_id: "node-b".to_string(),
        },
    ]);
    assert!(result.is_err());
}

#[test]
fn parse_assignments_rejects_invalid_node_or_sandbox_id() {
    let bad_node = parse_assignments(&[SandboxPlacement {
        sandbox_id: SandboxId::new().to_string(),
        node_id: "   ".to_string(),
    }]);
    assert!(bad_node.is_err());

    let bad_id = parse_assignments(&[SandboxPlacement {
        sandbox_id: "not-a-uuid".to_string(),
        node_id: "node-a".to_string(),
    }]);
    assert!(bad_id.is_err());
}

#[tokio::test]
async fn recovery_inventory_accepts_valid_policies_and_rejects_malformed_ones() {
    let projector = projector();

    assert!(projector
        .recovery_inventory(&ReplicatedSnapshot::default())
        .await
        .is_ok());

    let valid = ReplicatedSnapshot {
        policies: vec![replicated_policy(&SandboxId::new(), 1)],
        placements: Vec::new(),
    };
    assert!(projector.recovery_inventory(&valid).await.is_ok());

    let malformed = ReplicatedSnapshot {
        policies: vec![ReplicatedPolicy {
            sandbox_id: "not-a-uuid".to_string(),
            policy: replicated_policy(&SandboxId::new(), 1).policy,
        }],
        placements: Vec::new(),
    };
    assert!(projector.recovery_inventory(&malformed).await.is_err());
}

#[tokio::test]
async fn install_delta_rejects_invalid_placement_node() {
    let projector = projector();
    let mutation = ReplicaMutation::UpsertPlacement {
        placement: SandboxPlacement {
            sandbox_id: SandboxId::new().to_string(),
            node_id: "   ".to_string(),
        },
    };
    assert!(projector.install_delta(&mutation).await.is_err());
}

#[tokio::test]
async fn install_delta_rejects_duplicate_replace_placements() {
    let projector = projector();
    let id = SandboxId::new().to_string();
    let mutation = ReplicaMutation::ReplacePlacements {
        placements: vec![
            SandboxPlacement {
                sandbox_id: id.clone(),
                node_id: "node-a".to_string(),
            },
            SandboxPlacement {
                sandbox_id: id,
                node_id: "node-b".to_string(),
            },
        ],
    };
    assert!(projector.install_delta(&mutation).await.is_err());
}

#[tokio::test]
async fn install_delta_rejects_invalid_sandbox_ids() {
    let projector = projector();
    assert!(projector
        .install_delta(&ReplicaMutation::RemovePolicy {
            sandbox_id: "not-a-uuid".to_string(),
        })
        .await
        .is_err());
    assert!(projector
        .install_delta(&ReplicaMutation::RemovePlacement {
            sandbox_id: "not-a-uuid".to_string(),
        })
        .await
        .is_err());
}

#[tokio::test]
async fn follower_restores_credentials_from_the_hot_snapshot() {
    let authority = XdsAuthority::standalone();
    let control_plane = XdsControlPlane::new(authority, NodeVisibility::Unscoped);
    let projections = PolicyProjectionRegistry::default();
    let publisher = PolicyPublisher::new(control_plane.clone());
    let projector = ReplicaProjector::new(
        control_plane.clone(),
        publisher,
        projections,
        Arc::new(Mutex::new(())),
    );
    let snapshot = ReplicatedSnapshot {
        policies: vec![ReplicatedPolicy {
            sandbox_id: SandboxId::new().to_string(),
            policy: ApplySandboxPolicyRequest {
                generation: PolicyGeneration {
                    policy_hash: "d".repeat(64),
                    policy_version: 1,
                },
                allowlist_hosts: Vec::new(),
                credential_routes: vec![CredentialRoute {
                    id: "llm".to_string(),
                    kind: EgressKind::Llm,
                    exposure: EgressExposure::Placeholder,
                    match_host: "llm-egress.internal".to_string(),
                    path_mapping: PathMapping::PassthroughAny,
                    retry_mode: RetryMode::Disabled,
                    upstream_host: "api.example.com".to_string(),
                    upstream_port: 443,
                    upstream_tls: true,
                    vetted_addresses: Vec::new(),
                    inject_headers: vec![ResolvedHeader {
                        name: "authorization".to_string(),
                        value: "Bearer follower-secret".to_string(),
                    }],
                    remove_headers: vec!["authorization".to_string()],
                }],
                proxy_auth_token: Some("sandbox-proxy-secret".to_string()),
            },
        }],
        placements: Vec::new(),
    };

    projector
        .install_snapshot(&snapshot)
        .await
        .expect("install hydrated snapshot");
    let listener = control_plane
        .snapshot_resources(crate::xds::model::ResourceType::Listener)
        .await
        .into_iter()
        .next()
        .expect("listener resource");
    let secret = "Bearer follower-secret";
    assert!(listener
        .payload
        .value
        .windows(secret.len())
        .any(|window| window == secret.as_bytes()));
    let serialized = serde_json::to_vec(&snapshot).expect("serialize snapshot");
    assert!(serialized
        .windows(secret.len())
        .any(|window| window == secret.as_bytes()));
    assert!(!format!("{snapshot:?}").contains(secret));

    let mut delta_policy = snapshot.policies[0].clone();
    delta_policy.policy.generation.policy_hash = "f".repeat(64);
    delta_policy.policy.generation.policy_version = 2;
    delta_policy.policy.credential_routes[0].inject_headers[0].value =
        "Bearer rotated-follower-secret".to_string();
    let mutation = ReplicaMutation::UpsertPolicy {
        policy: delta_policy,
    };
    projector
        .install_delta(&mutation)
        .await
        .expect("install credential rotation delta");
    let listener = control_plane
        .snapshot_resources(crate::xds::model::ResourceType::Listener)
        .await
        .into_iter()
        .next()
        .expect("rotated listener resource");
    let rotated = "Bearer rotated-follower-secret";
    assert!(listener
        .payload
        .value
        .windows(rotated.len())
        .any(|window| window == rotated.as_bytes()));
    assert!(!format!("{mutation:?}").contains(rotated));
}
