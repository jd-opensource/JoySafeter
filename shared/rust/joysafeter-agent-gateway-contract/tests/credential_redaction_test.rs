use joysafeter_agent_gateway_contract::{
    ApplySandboxPolicyRequest, CredentialRoute, EgressExposure, EgressKind, PathMapping,
    PolicyGeneration, ResolvedHeader, RetryMode,
};

#[test]
fn credential_route_debug_output_never_contains_sensitive_material() {
    let route = CredentialRoute {
        id: "route".to_string(),
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
            value: "super-secret-route-value".to_string(),
        }],
        remove_headers: Vec::new(),
    };

    let rendered = format!("{route:?}");
    assert!(rendered.contains("authorization"));
    assert!(!rendered.contains("super-secret-route-value"));
}

#[test]
fn policy_request_debug_output_redacts_proxy_authentication() {
    let request = ApplySandboxPolicyRequest {
        generation: PolicyGeneration {
            policy_hash: "a".repeat(64),
            policy_version: 1,
        },
        allowlist_hosts: Vec::new(),
        credential_routes: Vec::new(),
        proxy_auth_token: Some("sandbox-proxy-secret".to_string()),
    };

    let rendered = format!("{request:?}");
    assert!(rendered.contains("<redacted>"));
    assert!(!rendered.contains("sandbox-proxy-secret"));
}
