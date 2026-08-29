use serde_json::{json, Value};

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::*;

pub const LISTENER_TYPE_URL: &str = "type.googleapis.com/envoy.config.listener.v3.Listener";
pub const CLUSTER_TYPE_URL: &str = "type.googleapis.com/envoy.config.cluster.v3.Cluster";

pub fn render_cluster_json(spec: &ClusterSpec) -> Value {
    let endpoint_hosts = if spec.vetted_addresses.is_empty() {
        vec![spec.upstream_host.clone()]
    } else {
        spec.vetted_addresses.clone()
    };
    let lb_endpoints = endpoint_hosts
        .into_iter()
        .map(|address| {
            json!({
                "endpoint": {
                    "address": {
                        "socket_address": {
                            "address": address,
                            "port_value": spec.upstream_port
                        }
                    }
                }
            })
        })
        .collect::<Vec<_>>();
    let static_cluster = !spec.vetted_addresses.is_empty();
    let mut cluster = json!({
        "@type": CLUSTER_TYPE_URL,
        "name": spec.name,
        "connect_timeout": "10s",
        "type": if static_cluster { "STATIC" } else { "LOGICAL_DNS" },
        "lb_policy": "ROUND_ROBIN",
        "load_assignment": {
            "cluster_name": spec.name,
            "endpoints": [{
                "lb_endpoints": lb_endpoints
            }]
        }
    });
    if !static_cluster {
        cluster["dns_lookup_family"] = json!("V4_ONLY");
        cluster["dns_refresh_rate"] = json!("2s");
        cluster["dns_failure_refresh_rate"] = json!({
            "base_interval": "0.5s",
            "max_interval": "2s"
        });
    }
    if spec.upstream_tls {
        cluster["transport_socket"] = json!({
            "name": "envoy.transport_sockets.tls",
            "typed_config": {
                "@type": "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                "sni": spec.upstream_host,
                "common_tls_context": {
                    "validation_context": {
                        "trusted_ca": { "filename": "/etc/ssl/certs/ca-certificates.crt" }
                    }
                }
            }
        });
    }
    cluster
}

// ---------------------------------------------------------------------------
// JSON listener rendering (filesystem backend)
// ---------------------------------------------------------------------------

/// Render a [`ListenerSpec`] to canonical Envoy Listener JSON.
pub fn render_listener_json(spec: &ListenerSpec) -> Value {
    match spec.kind {
        ListenerKind::Http => build_http_listener_json(
            &spec.sandbox_id,
            &spec.allowed_hosts,
            &spec.credentials,
            spec.proxy_auth_token.as_deref(),
        ),
    }
}

/// HTTP connection manager listener with domain-based allowlist.
fn build_http_listener_json(
    sandbox_id: &SandboxId,
    allowed_hosts: &[String],
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
) -> Value {
    let virtual_hosts = build_virtual_hosts_json(allowed_hosts, credentials, proxy_auth_token);
    let sandbox_uuid = sandbox_id.as_uuid();

    json!({
        "@type": LISTENER_TYPE_URL,
        "name": format!("{sandbox_uuid}_http"),
        "address": {
            "pipe": {
                "path": format!("/sockets/{sandbox_uuid}/http.sock"),
                "mode": 438
            }
        },
        "filter_chains": [{
            "filters": [{
                "name": "envoy.filters.network.http_connection_manager",
                "typed_config": {
                    "@type": "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                    "stat_prefix": format!("{sandbox_uuid}_http"),
                    "http_protocol_options": {
                        "allow_absolute_url": true
                    },
                    "stream_idle_timeout": "0s",
                    "access_log": [{
                        "name": "envoy.access_loggers.stdout",
                        "typed_config": {
                            "@type": "type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog",
                            "log_format": {
                                "json_format": {
                                    "ts": "%START_TIME%",
                                    "method": "%REQ(:METHOD)%",
                                    "authority": "%REQ(:AUTHORITY)%",
                                    "path": "%REQ(X-ENVOY-ORIGINAL-PATH?:PATH)%",
                                    "status": "%RESPONSE_CODE%",
                                    "flags": "%RESPONSE_FLAGS%",
                                    "response_code_details": "%RESPONSE_CODE_DETAILS%",
                                    "upstream_transport_failure_reason": "%UPSTREAM_TRANSPORT_FAILURE_REASON%",
                                    "upstream": "%UPSTREAM_HOST%",
                                    "upstream_host": "%UPSTREAM_HOST%",
                                    "cluster": "%UPSTREAM_CLUSTER%",
                                    "upstream_cluster": "%UPSTREAM_CLUSTER%",
                                    "attempt_count": "%UPSTREAM_REQUEST_ATTEMPT_COUNT%",
                                    "duration_ms": "%DURATION%",
                                    "listener": format!("{sandbox_uuid}_http")
                                }
                            }
                        }
                    }],
                    "upgrade_configs": [{
                        "upgrade_type": "CONNECT"
                    }],
                    "route_config": {
                        "virtual_hosts": virtual_hosts
                    },
                    "http_filters": [
                        {
                            "name": "envoy.filters.http.dynamic_forward_proxy",
                            "typed_config": {
                                "@type": "type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig",
                                "dns_cache_config": {
                                    "name": "dynamic_forward_proxy_cache",
                                    "dns_lookup_family": "V4_ONLY"
                                }
                            }
                        },
                        {
                            "name": "envoy.filters.http.router",
                            "typed_config": {
                                "@type": "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router"
                            }
                        }
                    ]
                }
            }]
        }]
    })
}

/// Build the virtual_hosts array for the HTTP listener.
///
/// Order matters — Envoy evaluates virtual hosts by most-specific domain match,
/// and routes within a vhost are first-match. Credential-injection vhosts match
/// the **real** upstream host, so a host with an injected credential gets its own
/// vhost (superseding the plain allowlist entry for that host); unmatched paths
/// on that host still egress plainly.
pub(crate) fn build_virtual_hosts_json(
    allowed_hosts: &[String],
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
) -> Vec<Value> {
    let mut vhosts = Vec::new();

    // Credential-injection vhosts, one per real upstream host. Routes that share
    // a host (e.g. several MCP servers on the same host) are grouped and ordered
    // longest-prefix-first so `/sse` wins over `/`.
    for (match_host, routes) in group_credentials_by_host(credentials) {
        let json_routes: Vec<Value> = routes
            .iter()
            .map(|r| {
                let headers: Vec<Value> = r
                    .inject_headers
                    .iter()
                    .map(|(k, v)| {
                        json!({
                            "header": { "key": k, "value": escape_envoy_header_value(v) },
                            "append_action": "OVERWRITE_IF_EXISTS_OR_ADD"
                        })
                    })
                    .collect();
                let mut headers_to_remove = if r.remove_headers.is_empty() {
                    auth_headers_to_remove(&r.inject_headers)
                } else {
                    r.remove_headers.clone()
                };
                if !headers_to_remove
                    .iter()
                    .any(|h| h.eq_ignore_ascii_case("proxy-authorization"))
                {
                    headers_to_remove.push("proxy-authorization".to_string());
                }
                let is_transparent = r.exposure == EgressExposure::Transparent;
                let mut route_json = json!({
                    "cluster": r.cluster_name,
                    "timeout": "0s",
                });
                let route_object = route_json
                    .as_object_mut()
                    .expect("route projection is an object");
                if !is_transparent {
                    route_object.insert(
                        "host_rewrite_literal".to_string(),
                        json!(upstream_authority(
                            &r.upstream_host,
                            r.upstream_port,
                            r.upstream_tls,
                        )),
                    );
                }
                match &r.path_mapping {
                    EgressPathMapping::Passthrough { .. } => {}
                    EgressPathMapping::RewriteExact { upstream_path, .. } => {
                        route_object.insert("prefix_rewrite".to_string(), json!(upstream_path));
                    }
                    EgressPathMapping::RewritePrefix {
                        upstream_prefix, ..
                    } => {
                        route_object.insert("prefix_rewrite".to_string(), json!(upstream_prefix));
                    }
                }
                if r.retry_mode == EgressRetryMode::SafeIdempotent {
                    route_object.insert(
                        "retry_policy".to_string(),
                        json!({
                            "retry_on": "5xx,reset,connect-failure",
                            "num_retries": 2
                        }),
                    );
                }
                let mut match_json = match &r.path_mapping {
                    EgressPathMapping::Passthrough {
                        matcher: EgressPathMatcher::Any,
                    } => json!({ "prefix": "/" }),
                    EgressPathMapping::Passthrough {
                        matcher: EgressPathMatcher::Exact(path),
                    }
                    | EgressPathMapping::RewriteExact {
                        exposed_path: path, ..
                    } => json!({ "path": path }),
                    EgressPathMapping::Passthrough {
                        matcher: EgressPathMatcher::Prefix(prefix),
                    }
                    | EgressPathMapping::RewritePrefix {
                        exposed_prefix: prefix,
                        ..
                    } => json!({ "prefix": prefix }),
                };
                add_proxy_auth_match(&mut match_json, proxy_auth_token);
                json!({
                    "match": match_json,
                    "route": route_json,
                    "request_headers_to_add": headers,
                    "request_headers_to_remove": headers_to_remove
                })
            })
            .collect();

        // Domains include the bare host + standard port variants (:80/:443).
        // For transparent egress routes targeting non-standard ports, also add
        // :<port> so Envoy matches the Host header that includes the port.
        let mut domains = vec![
            json!(&match_host),
            json!(format!("{match_host}:80")),
            json!(format!("{match_host}:443")),
        ];
        for r in &routes {
            if r.upstream_port != 80 && r.upstream_port != 443 {
                let with_port = format!("{match_host}:{}", r.upstream_port);
                if !domains.iter().any(|d| d.as_str() == Some(&with_port)) {
                    domains.push(json!(with_port));
                }
            }
        }

        vhosts.push(json!({
            "name": format!("egress_{}", match_host.replace(['.', ':'], "_")),
            "domains": domains,
            "routes": json_routes
        }));
    }

    if !allowed_hosts.is_empty() {
        let mut domains = Vec::new();
        for host in allowed_hosts {
            domains.push(json!(host));
            if !host.contains(':') {
                domains.push(json!(format!("{host}:443")));
                domains.push(json!(format!("{host}:80")));
            }
        }

        vhosts.push(json!({
            "name": "allowed",
            "domains": domains,
            "routes": [
                {
                    "match": route_match_with_proxy_auth(json!({ "connect_matcher": {} }), proxy_auth_token),
                    "route": {
                        "cluster": "dynamic_forward_proxy",
                        "upgrade_configs": [{
                            "upgrade_type": "CONNECT",
                            "connect_config": {}
                        }]
                    },
                    "request_headers_to_remove": ["proxy-authorization"]
                },
                {
                    "match": route_match_with_proxy_auth(json!({ "prefix": "/" }), proxy_auth_token),
                    "route": {
                        "cluster": "dynamic_forward_proxy",
                        "retry_policy": {
                            "retry_on": "5xx,reset,connect-failure",
                            "num_retries": 2
                        }
                    },
                    "request_headers_to_remove": ["proxy-authorization"]
                }
            ]
        }));
    }

    // Catch-all: deny everything not explicitly allowed.
    vhosts.push(json!({
        "name": "deny_all",
        "domains": ["*"],
        "routes": [{
            "match": { "prefix": "/" },
            "direct_response": {
                "status": 403,
                "body": { "inline_string": "Host not in allowlist" }
            }
        }]
    }));

    vhosts
}

fn add_proxy_auth_match(match_json: &mut Value, proxy_auth_token: Option<&str>) {
    let Some(token) = proxy_auth_token.filter(|token| !token.is_empty()) else {
        return;
    };
    if let Some(obj) = match_json.as_object_mut() {
        obj.insert(
            "headers".to_string(),
            json!([{
                "name": "proxy-authorization",
                "string_match": { "exact": proxy_authorization_value(token) }
            }]),
        );
    }
}

fn route_match_with_proxy_auth(mut match_json: Value, proxy_auth_token: Option<&str>) -> Value {
    add_proxy_auth_match(&mut match_json, proxy_auth_token);
    match_json
}
