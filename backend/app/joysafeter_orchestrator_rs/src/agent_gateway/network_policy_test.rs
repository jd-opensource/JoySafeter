use super::*;
use crate::kernel::network_policy::envoy_model::{
    EgressExposure as DomainExposure, EgressKind as DomainKind,
};
use crate::kernel::network_policy::NetworkPolicyGeneration;

#[test]
fn transport_conversion_preserves_policy_semantics_and_redacts_secrets() {
    let request = into_request(
        NetworkPolicyGeneration {
            policy_hash: "a".repeat(64),
            policy_version: 7,
        },
        SandboxEgressPolicy {
            allowlist_hosts: vec!["docs.example.com".to_string()],
            credential_routes: vec![EgressCredentialRoute {
                id: "llm-primary".to_string(),
                kind: DomainKind::Llm,
                exposure: DomainExposure::Placeholder,
                match_host: "llm-egress.internal".to_string(),
                path_mapping: EgressPathMapping::RewritePrefix {
                    exposed_prefix: "/v1/".to_string(),
                    upstream_prefix: "/api/".to_string(),
                },
                retry_mode: EgressRetryMode::SafeIdempotent,
                upstream_host: "api.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: "dynamic_forward_proxy_tls".to_string(),
                vetted_addresses: vec!["192.0.2.10".to_string()],
                inject_headers: vec![(
                    "authorization".to_string(),
                    "secret-upstream-token".to_string(),
                )],
                remove_headers: vec!["x-api-key".to_string()],
            }],
            proxy_auth_token: Some("secret-proxy-token".to_string()),
            ephemeral_credentials_valid_for_seconds: Some(300),
        },
    );

    assert_eq!(request.generation.policy_version, 7);
    assert_eq!(request.credential_routes.len(), 1);
    assert_eq!(
        request.proxy_auth_token.as_deref(),
        Some("secret-proxy-token")
    );
    assert!(matches!(
        request.credential_routes[0].path_mapping,
        PathMapping::RewritePrefix { .. }
    ));
    assert_eq!(request.credential_routes[0].inject_headers.len(), 1);
    assert_eq!(
        request.credential_routes[0].inject_headers[0].value,
        "secret-upstream-token"
    );
    let debug = format!("{request:?}");
    assert!(!debug.contains("secret-upstream-token"));
    assert!(!debug.contains("secret-proxy-token"));
}

#[test]
fn xds_transport_preserves_resolved_header_material_without_logging_it() {
    let request = into_request(
        NetworkPolicyGeneration {
            policy_hash: "b".repeat(64),
            policy_version: 8,
        },
        SandboxEgressPolicy {
            allowlist_hosts: Vec::new(),
            credential_routes: vec![EgressCredentialRoute {
                id: "identity".to_string(),
                kind: DomainKind::External,
                exposure: DomainExposure::Placeholder,
                match_host: "external-egress.internal".to_string(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Any,
                },
                retry_mode: EgressRetryMode::Disabled,
                upstream_host: "api.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: "dynamic_forward_proxy_tls".to_string(),
                vetted_addresses: Vec::new(),
                inject_headers: vec![("authorization".to_string(), "identity-token".to_string())],
                remove_headers: vec!["authorization".to_string()],
            }],
            proxy_auth_token: None,
            ephemeral_credentials_valid_for_seconds: Some(300),
        },
    );

    assert_eq!(request.credential_routes[0].inject_headers.len(), 1);
    assert_eq!(
        request.credential_routes[0].inject_headers[0].value,
        "identity-token"
    );
    assert!(!format!("{request:?}").contains("identity-token"));
}

#[test]
fn identity_policy_transports_user_and_agent_tokens_but_never_a_bot_token() {
    let request = into_request(
        NetworkPolicyGeneration {
            policy_hash: "c".repeat(64),
            policy_version: 9,
        },
        SandboxEgressPolicy {
            allowlist_hosts: vec![],
            credential_routes: vec![EgressCredentialRoute {
                id: "external-identity:crm:0".to_string(),
                kind: DomainKind::External,
                exposure: DomainExposure::Transparent,
                match_host: "crm.example.com".to_string(),
                path_mapping: EgressPathMapping::Passthrough {
                    matcher: EgressPathMatcher::Any,
                },
                retry_mode: EgressRetryMode::Disabled,
                upstream_host: "crm.example.com".to_string(),
                upstream_port: 443,
                upstream_tls: true,
                cluster_name: "dynamic_forward_proxy_tls".to_string(),
                vetted_addresses: vec![],
                inject_headers: vec![
                    (
                        "X-Security-AgentToken".to_string(),
                        "agent-token-secret".to_string(),
                    ),
                    ("Cookie".to_string(), "sso=user-token-secret".to_string()),
                ],
                remove_headers: vec!["x-security-agenttoken".to_string(), "cookie".to_string()],
            }],
            proxy_auth_token: None,
            ephemeral_credentials_valid_for_seconds: Some(300),
        },
    );

    let route = &request.credential_routes[0];
    assert_eq!(
        route
            .inject_headers
            .iter()
            .map(|header| header.name.as_str())
            .collect::<Vec<_>>(),
        ["X-Security-AgentToken", "Cookie"]
    );
    let serialized = serde_json::to_string(&request).expect("serialize policy request");
    assert!(serialized.contains("agent-token-secret"));
    assert!(serialized.contains("user-token-secret"));
    assert!(!serialized.contains("bot-token-secret"));
    let debug = format!("{request:?}");
    assert!(!debug.contains("agent-token-secret"));
    assert!(!debug.contains("user-token-secret"));
}
