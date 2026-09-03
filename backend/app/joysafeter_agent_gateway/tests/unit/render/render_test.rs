use super::listener::build_virtual_hosts_proto;
use super::*;
use crate::domain::egress_policy::{
    proxy_authorization_value, ClusterSpec, EgressExposure, EgressPathMapping, EgressPathMatcher,
    EgressRetryMode, EgressRouteSpec, MCP_EGRESS_HOST,
};
use crate::ids::SandboxId;
use envoy_types::pb::envoy::config::cluster::v3::{cluster, Cluster};
use envoy_types::pb::envoy::config::route::v3::{header_matcher, route, route_action};
use envoy_types::pb::envoy::extensions::transport_sockets::tls::v3::UpstreamTlsContext;
use envoy_types::pb::envoy::r#type::matcher::v3::string_matcher;

fn route(path_mapping: EgressPathMapping) -> EgressRouteSpec {
    EgressRouteSpec {
        id: "mcp-primary".to_string(),
        exposure: EgressExposure::Placeholder,
        match_host: MCP_EGRESS_HOST.to_string(),
        path_mapping,
        retry_mode: EgressRetryMode::Disabled,
        upstream_host: "mcp.example.com".to_string(),
        upstream_port: 8443,
        upstream_tls: true,
        cluster_name: "mcp_pinned".to_string(),
        inject_headers: Vec::new(),
        remove_headers: Vec::new(),
    }
}

#[test]
fn injects_resolved_headers_into_the_route() {
    let mut credential_route = route(EgressPathMapping::Passthrough {
        matcher: EgressPathMatcher::Any,
    });
    credential_route.inject_headers = vec![(
        "authorization".to_string(),
        "Bearer direct-secret".to_string(),
    )];
    credential_route.remove_headers = vec![
        "authorization".to_string(),
        "proxy-authorization".to_string(),
    ];

    let vhosts = build_virtual_hosts_proto(&[], &[credential_route], None);
    let rendered = &vhosts[0].routes[0];
    let injected = rendered.request_headers_to_add[0]
        .header
        .as_ref()
        .expect("injected header");
    assert_eq!(injected.key, "authorization");
    assert_eq!(injected.value, "Bearer direct-secret");
    assert_eq!(
        rendered.request_headers_to_remove,
        ["authorization", "proxy-authorization"]
    );
    assert!(rendered.typed_per_filter_config.is_empty());
}

#[test]
fn removes_competing_auth_and_proxy_headers_by_default() {
    let mut credential_route = route(EgressPathMapping::Passthrough {
        matcher: EgressPathMatcher::Any,
    });
    credential_route.inject_headers = vec![(
        "authorization".to_string(),
        "Bearer direct-secret".to_string(),
    )];

    let vhosts = build_virtual_hosts_proto(&[], &[credential_route], None);
    let rendered = &vhosts[0].routes[0];

    assert_eq!(
        rendered.request_headers_to_remove,
        [
            "x-api-key",
            "api-key",
            "x-goog-api-key",
            "proxy-authorization",
        ]
    );
}

#[test]
fn credential_routes_precede_allowlist_and_deny_all() {
    let vhosts = build_virtual_hosts_proto(
        &["docs.example.com".to_string()],
        &[route(EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any,
        })],
        None,
    );

    let names = vhosts
        .iter()
        .map(|vhost| vhost.name.as_str())
        .collect::<Vec<_>>();
    assert_eq!(names, ["egress_mcp-egress_internal", "allowed", "deny_all"]);
}

#[test]
fn exact_mcp_route_preserves_authority_and_disables_retries() {
    let vhosts = build_virtual_hosts_proto(
        &[],
        &[route(EgressPathMapping::RewriteExact {
            exposed_path: "/r/opaque".to_string(),
            upstream_path: "/mcp".to_string(),
        })],
        None,
    );
    let rendered = &vhosts[0].routes[0];
    assert!(matches!(
        rendered.r#match.as_ref().and_then(|matcher| matcher.path_specifier.as_ref()),
        Some(envoy_types::pb::envoy::config::route::v3::route_match::PathSpecifier::Path(path))
            if path == "/r/opaque"
    ));
    let action = match rendered.action.as_ref() {
        Some(route::Action::Route(action)) => action,
        _ => panic!("expected route action"),
    };
    assert!(matches!(
        action.host_rewrite_specifier.as_ref(),
        Some(route_action::HostRewriteSpecifier::HostRewriteLiteral(authority))
            if authority == "mcp.example.com:8443"
    ));
    assert_eq!(action.prefix_rewrite, "/mcp");
    assert!(action.retry_policy.is_none());
}

#[test]
fn proxy_authentication_is_required_for_credential_and_allowlist_routes() {
    let expected = proxy_authorization_value("runner-secret");
    let vhosts = build_virtual_hosts_proto(
        &["docs.example.com".to_string()],
        &[route(EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any,
        })],
        Some("runner-secret"),
    );

    for route in [&vhosts[0].routes[0], &vhosts[1].routes[0]] {
        let matcher = &route.r#match.as_ref().expect("route match").headers[0];
        assert_eq!(matcher.name, "proxy-authorization");
        assert!(matches!(
            matcher.header_match_specifier.as_ref(),
            Some(header_matcher::HeaderMatchSpecifier::StringMatch(value))
                if value.match_pattern
                    == Some(string_matcher::MatchPattern::Exact(expected.clone()))
        ));
    }
}

#[test]
fn vetted_addresses_render_static_cluster_with_original_tls_sni() {
    let cluster_spec = ClusterSpec {
        sandbox_id: SandboxId::new(),
        name: "mcp_pinned".to_string(),
        upstream_host: "mcp.example.com".to_string(),
        upstream_port: 443,
        upstream_tls: true,
        vetted_addresses: vec!["192.0.2.10".to_string(), "2001:db8::10".to_string()],
    };
    let encoded = encode_cluster_any(&cluster_spec).expect("encode cluster");
    let cluster = Cluster::decode(encoded.value.as_slice()).expect("decode cluster");
    assert_eq!(
        cluster.cluster_discovery_type,
        Some(cluster::ClusterDiscoveryType::Type(
            cluster::DiscoveryType::Static as i32
        ))
    );
    assert_eq!(
        cluster
            .load_assignment
            .as_ref()
            .expect("load assignment")
            .endpoints[0]
            .lb_endpoints
            .len(),
        2
    );
    let tls_any = match cluster
        .transport_socket
        .expect("TLS transport socket")
        .config_type
    {
        Some(
            envoy_types::pb::envoy::config::core::v3::transport_socket::ConfigType::TypedConfig(
                any,
            ),
        ) => any,
        _ => panic!("expected typed TLS config"),
    };
    let tls = UpstreamTlsContext::decode(tls_any.value.as_slice()).expect("decode TLS config");
    assert_eq!(tls.sni, "mcp.example.com");
}
