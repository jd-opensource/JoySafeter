use super::*;
use joysafeter_agent_gateway_contract::{ApplySandboxPolicyRequest, PolicyGeneration};

#[test]
fn replica_wire_model_has_only_policy_and_placement_collections() {
    let snapshot = ReplicatedSnapshot {
        policies: vec![ReplicatedPolicy {
            sandbox_id: "0198cafe-0000-7000-8000-000000000001".to_string(),
            policy: ApplySandboxPolicyRequest {
                generation: PolicyGeneration {
                    policy_hash: "a".repeat(64),
                    policy_version: 1,
                },
                allowlist_hosts: vec!["api.example.com".to_string()],
                credential_routes: Vec::new(),
                proxy_auth_token: None,
            },
        }],
        placements: Vec::new(),
    };

    let json = serde_json::to_value(snapshot).expect("serialize snapshot");
    let object = json.as_object().expect("snapshot object");
    assert_eq!(object.len(), 2);
    assert!(object.contains_key("policies"));
    assert!(object.contains_key("placements"));
}
