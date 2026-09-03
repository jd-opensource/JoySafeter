use super::credentials::group_credentials_by_host;
use super::*;
use crate::ids::SandboxId;

fn credential_route() -> EgressCredentialRoute {
    EgressCredentialRoute {
        id: "llm-primary".to_string(),
        kind: EgressKind::Llm,
        exposure: EgressExposure::Placeholder,
        match_host: LLM_EGRESS_HOST.to_string(),
        path_mapping: EgressPathMapping::RewritePrefix {
            exposed_prefix: "/v1/".to_string(),
            upstream_prefix: "/v1/".to_string(),
        },
        retry_mode: EgressRetryMode::SafeIdempotent,
        upstream_host: "api.example.com".to_string(),
        upstream_port: 443,
        upstream_tls: true,
        cluster_name: "dynamic_forward_proxy_tls".to_string(),
        vetted_addresses: Vec::new(),
        inject_headers: vec![(
            "authorization".to_string(),
            "Bearer upstream-secret".to_string(),
        )],
        remove_headers: Vec::new(),
    }
}

#[test]
fn rejects_allowlist_that_can_bypass_credential_route() {
    let sandbox_id = SandboxId::new();
    for allowed_host in [LLM_EGRESS_HOST, "*.internal"] {
        let policy = SandboxEgressPolicy {
            allowlist_hosts: vec![allowed_host.to_string()],
            credential_routes: vec![credential_route()],
            proxy_auth_token: None,
        };
        let error = validate_egress_policy(&sandbox_id, &policy)
            .expect_err("overlapping allowlist must be rejected")
            .to_string();
        assert!(error.contains("overlaps credential-injection host"));
    }
}

#[test]
fn policy_summary_contains_only_injection_names() {
    let sandbox_id = SandboxId::new();
    let policy = SandboxEgressPolicy {
        allowlist_hosts: Vec::new(),
        credential_routes: vec![credential_route()],
        proxy_auth_token: Some("proxy-secret".to_string()),
    };
    let summary = rendered_egress_policy_summary(&sandbox_id, &policy).to_string();
    assert!(!summary.contains("proxy-secret"));
    assert!(!summary.contains("upstream-secret"));
    assert!(summary.contains("inject_header_names"));
}

#[test]
fn same_host_routes_are_ordered_most_specific_first() {
    let mut short = credential_route();
    short.id = "short".to_string();
    short.match_host = "service.example.com".to_string();
    short.path_mapping = EgressPathMapping::Passthrough {
        matcher: EgressPathMatcher::Prefix("/api/".to_string()),
    };
    let mut long = short.clone();
    long.id = "long".to_string();
    long.path_mapping = EgressPathMapping::Passthrough {
        matcher: EgressPathMatcher::Prefix("/api/admin/".to_string()),
    };

    let grouped = group_credentials_by_host(&[short, long]);
    assert_eq!(grouped.len(), 1);
    assert_eq!(grouped[0].1[0].id, "long");
    assert_eq!(grouped[0].1[1].id, "short");
}
