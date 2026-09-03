use std::collections::HashMap;

use agent_identity_trait::IdentityEgressRequestTarget;

use super::{host_matches, normalize_host_pattern, AgentIdentityServiceRegistry, TrustedService};

fn target(host: &str, port: u16, tls: bool) -> IdentityEgressRequestTarget {
    IdentityEgressRequestTarget {
        route_id: "route-1".to_string(),
        endpoint: format!("{}://{host}", if tls { "https" } else { "http" }),
        host: host.to_string(),
        port,
        tls,
    }
}

#[test]
fn wildcard_matches_only_subdomains() {
    assert!(host_matches(
        "api.trusted.example.com",
        "*.trusted.example.com"
    ));
    assert!(host_matches(
        "a.b.trusted.example.com",
        "*.trusted.example.com"
    ));
    assert!(!host_matches(
        "trusted.example.com",
        "*.trusted.example.com"
    ));
    assert!(!host_matches(
        "eviltrusted.example.com",
        "*.trusted.example.com"
    ));
}

#[test]
fn host_patterns_are_normalized_and_reject_unsafe_wildcards() {
    assert_eq!(
        normalize_host_pattern("*.Trusted.Example.COM.").unwrap(),
        "*.trusted.example.com"
    );
    for invalid in [
        "*",
        "localhost",
        "*.com",
        "api.*.example.com",
        "*.127.0.0.1",
        "-api.example.com",
    ] {
        assert!(normalize_host_pattern(invalid).is_err(), "{invalid}");
    }
}

#[test]
fn dynamic_registry_matches_provider_host_port_and_transport() {
    let registry = AgentIdentityServiceRegistry::default();
    registry.replace(HashMap::from([(
        "trusted".to_string(),
        TrustedService {
            provider: "jd".to_string(),
            host_pattern: "*.trusted.example.com".to_string(),
            port: 443,
            tls: true,
        },
    )]));

    assert!(registry.allows("jd", &target("api.trusted.example.com", 443, true)));
    assert!(!registry.allows("jd", &target("trusted.example.com", 443, true)));
    assert!(!registry.allows("jd", &target("api.trusted.example.com", 80, false)));
    assert!(!registry.allows("other", &target("api.trusted.example.com", 443, true)));
    assert_eq!(registry.len(), 1);
}

#[test]
fn static_fallback_preserves_legacy_host_only_matching() {
    let registry = AgentIdentityServiceRegistry::from_static_hosts(
        "jd",
        &[
            "api.example.com".to_string(),
            "*.trusted.example.com".to_string(),
        ],
    );

    assert!(registry.allows("jd", &target("api.example.com", 80, false)));
    assert!(registry.allows("jd", &target("one.trusted.example.com", 443, true)));
    assert!(!registry.allows("jd", &target("example.com", 443, true)));
}
