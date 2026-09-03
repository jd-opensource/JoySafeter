use joysafeter_agent_gateway_contract::{
    CredentialRoute, EgressExposure, EgressKind, PathMapping, PolicyGeneration, ResolvedHeader,
    RetryMode,
};

use super::*;

#[test]
fn rejects_invalid_generation() {
    let request = ApplySandboxPolicyRequest {
        generation: PolicyGeneration {
            policy_hash: "not-a-sha256".to_string(),
            policy_version: 1,
        },
        allowlist_hosts: Vec::new(),
        credential_routes: Vec::new(),
        proxy_auth_token: None,
    };
    assert!(ValidatedPolicy::from_request(SandboxId::new(), request).is_err());
}

fn request_with_material(name: &str) -> ApplySandboxPolicyRequest {
    ApplySandboxPolicyRequest {
        generation: PolicyGeneration {
            policy_hash: "a".repeat(64),
            policy_version: 1,
        },
        allowlist_hosts: Vec::new(),
        credential_routes: vec![CredentialRoute {
            id: "identity".to_string(),
            kind: EgressKind::External,
            exposure: EgressExposure::Placeholder,
            match_host: "external-egress.internal".to_string(),
            path_mapping: PathMapping::PassthroughAny,
            retry_mode: RetryMode::Disabled,
            upstream_host: "api.example.com".to_string(),
            upstream_port: 443,
            upstream_tls: true,
            vetted_addresses: Vec::new(),
            inject_headers: vec![ResolvedHeader {
                name: name.to_string(),
                value: "Bearer identity-secret".to_string(),
            }],
            remove_headers: vec!["authorization".to_string()],
        }],
        proxy_auth_token: Some("sandbox-proxy-secret".to_string()),
    }
}

#[test]
fn accepts_resolved_material() {
    let validated =
        ValidatedPolicy::from_request(SandboxId::new(), request_with_material("authorization"))
            .expect("valid direct-xDS request");

    assert_eq!(
        validated.policy.credential_routes[0].inject_headers[0].1,
        "Bearer identity-secret"
    );
    assert!(!format!("{validated:?}").contains("identity-secret"));
    assert!(!format!("{validated:?}").contains("sandbox-proxy-secret"));
}

#[test]
fn rejects_header_values_with_control_characters_without_leaking_them() {
    let secret = "Bearer identity-secret\nforged: value";
    let mut request = request_with_material("authorization");
    request.credential_routes[0].inject_headers[0].value = secret.to_string();

    let error = ValidatedPolicy::from_request(SandboxId::new(), request)
        .expect_err("control characters must be rejected");

    assert!(error.contains("control characters"));
    assert!(!error.contains(secret));
}
