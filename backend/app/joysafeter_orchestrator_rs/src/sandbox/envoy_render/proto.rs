use std::collections::HashMap;

use envoy_types::pb::google::protobuf::Any;
use prost::Message;

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::*;

use super::json::{CLUSTER_TYPE_URL, LISTENER_TYPE_URL};

fn protobuf_string_value(value: impl Into<String>) -> envoy_types::pb::google::protobuf::Value {
    envoy_types::pb::google::protobuf::Value {
        kind: Some(envoy_types::pb::google::protobuf::value::Kind::StringValue(
            value.into(),
        )),
    }
}

fn access_log_json_format(listener: String) -> envoy_types::pb::google::protobuf::Struct {
    envoy_types::pb::google::protobuf::Struct {
        fields: HashMap::from([
            ("ts".to_string(), protobuf_string_value("%START_TIME%")),
            (
                "method".to_string(),
                protobuf_string_value("%REQ(:METHOD)%"),
            ),
            (
                "authority".to_string(),
                protobuf_string_value("%REQ(:AUTHORITY)%"),
            ),
            (
                "path".to_string(),
                protobuf_string_value("%REQ(X-ENVOY-ORIGINAL-PATH?:PATH)%"),
            ),
            (
                "status".to_string(),
                protobuf_string_value("%RESPONSE_CODE%"),
            ),
            (
                "flags".to_string(),
                protobuf_string_value("%RESPONSE_FLAGS%"),
            ),
            (
                "response_code_details".to_string(),
                protobuf_string_value("%RESPONSE_CODE_DETAILS%"),
            ),
            (
                "upstream_transport_failure_reason".to_string(),
                protobuf_string_value("%UPSTREAM_TRANSPORT_FAILURE_REASON%"),
            ),
            (
                "upstream".to_string(),
                protobuf_string_value("%UPSTREAM_HOST%"),
            ),
            (
                "upstream_host".to_string(),
                protobuf_string_value("%UPSTREAM_HOST%"),
            ),
            (
                "cluster".to_string(),
                protobuf_string_value("%UPSTREAM_CLUSTER%"),
            ),
            (
                "upstream_cluster".to_string(),
                protobuf_string_value("%UPSTREAM_CLUSTER%"),
            ),
            (
                "attempt_count".to_string(),
                protobuf_string_value("%UPSTREAM_REQUEST_ATTEMPT_COUNT%"),
            ),
            (
                "duration_ms".to_string(),
                protobuf_string_value("%DURATION%"),
            ),
            (
                "bytes_in".to_string(),
                protobuf_string_value("%BYTES_RECEIVED%"),
            ),
            (
                "bytes_out".to_string(),
                protobuf_string_value("%BYTES_SENT%"),
            ),
            ("listener".to_string(), protobuf_string_value(listener)),
        ]),
    }
}
pub fn encode_listener_any(spec: &ListenerSpec) -> anyhow::Result<Any> {
    use envoy_types::pb::envoy::config::listener::v3::Listener;

    let listener: Listener = match spec.kind {
        ListenerKind::Http => build_http_listener_proto(
            &spec.sandbox_id,
            &spec.allowed_hosts,
            &spec.credentials,
            spec.proxy_auth_token.as_deref(),
        ),
    };
    let mut buf = Vec::new();
    listener.encode(&mut buf)?;
    Ok(Any {
        type_url: LISTENER_TYPE_URL.to_string(),
        value: buf,
    })
}

/// Encode a [`ClusterSpec`] into a `google.protobuf.Any` wrapping a typed Envoy
/// Cluster, preserving the same STATIC-vs-LOGICAL_DNS decision as JSON mode.
pub fn encode_cluster_any(spec: &ClusterSpec) -> anyhow::Result<Any> {
    use envoy_types::pb::envoy::config::cluster::v3::{cluster, Cluster};
    use envoy_types::pb::envoy::config::core::v3::{
        address, socket_address, Address, SocketAddress,
    };
    use envoy_types::pb::envoy::config::endpoint::v3::{
        lb_endpoint, ClusterLoadAssignment, Endpoint, LbEndpoint, LocalityLbEndpoints,
    };

    let endpoint_hosts = if spec.vetted_addresses.is_empty() {
        vec![spec.upstream_host.clone()]
    } else {
        spec.vetted_addresses.clone()
    };
    let endpoints = endpoint_hosts
        .into_iter()
        .map(|address_value| LbEndpoint {
            host_identifier: Some(lb_endpoint::HostIdentifier::Endpoint(Endpoint {
                address: Some(Address {
                    address: Some(address::Address::SocketAddress(SocketAddress {
                        address: address_value,
                        port_specifier: Some(socket_address::PortSpecifier::PortValue(
                            spec.upstream_port as u32,
                        )),
                        ..Default::default()
                    })),
                }),
                ..Default::default()
            })),
            ..Default::default()
        })
        .collect();
    let static_cluster = !spec.vetted_addresses.is_empty();

    let mut cl = Cluster {
        name: spec.name.clone(),
        connect_timeout: Some(envoy_types::pb::google::protobuf::Duration {
            seconds: 10,
            nanos: 0,
        }),
        cluster_discovery_type: Some(cluster::ClusterDiscoveryType::Type(if static_cluster {
            cluster::DiscoveryType::Static as i32
        } else {
            cluster::DiscoveryType::LogicalDns as i32
        })),
        dns_refresh_rate: (!static_cluster).then_some(
            envoy_types::pb::google::protobuf::Duration {
                seconds: 2,
                nanos: 0,
            },
        ),
        dns_failure_refresh_rate: (!static_cluster).then_some(cluster::RefreshRate {
            base_interval: Some(envoy_types::pb::google::protobuf::Duration {
                seconds: 0,
                nanos: 500_000_000,
            }),
            max_interval: Some(envoy_types::pb::google::protobuf::Duration {
                seconds: 2,
                nanos: 0,
            }),
        }),
        load_assignment: Some(ClusterLoadAssignment {
            cluster_name: spec.name.clone(),
            endpoints: vec![LocalityLbEndpoints {
                lb_endpoints: endpoints,
                ..Default::default()
            }],
            ..Default::default()
        }),
        ..Default::default()
    };

    if spec.upstream_tls {
        use envoy_types::pb::envoy::config::core::v3::{
            data_source, transport_socket, DataSource, TransportSocket,
        };
        use envoy_types::pb::envoy::extensions::transport_sockets::tls::v3::{
            common_tls_context::ValidationContextType, CertificateValidationContext,
            CommonTlsContext, UpstreamTlsContext,
        };

        let tls = UpstreamTlsContext {
            sni: spec.upstream_host.clone(),
            common_tls_context: Some(CommonTlsContext {
                validation_context_type: Some(ValidationContextType::ValidationContext(
                    CertificateValidationContext {
                        trusted_ca: Some(DataSource {
                            specifier: Some(data_source::Specifier::Filename(
                                "/etc/ssl/certs/ca-certificates.crt".to_string(),
                            )),
                            ..Default::default()
                        }),
                        ..Default::default()
                    },
                )),
                ..Default::default()
            }),
            ..Default::default()
        };
        cl.transport_socket = Some(TransportSocket {
            name: "envoy.transport_sockets.tls".to_string(),
            config_type: Some(transport_socket::ConfigType::TypedConfig(pack_any(
                "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
                &tls,
            ))),
        });
    }

    let mut buf = Vec::new();
    cl.encode(&mut buf)?;
    Ok(Any {
        type_url: CLUSTER_TYPE_URL.to_string(),
        value: buf,
    })
}

/// Helper: wrap a prost message in an `Any` with the given type URL.
fn pack_any<M: Message>(type_url: &str, msg: &M) -> Any {
    let mut buf = Vec::new();
    // encode into a Vec never fails for a valid message
    msg.encode(&mut buf).expect("prost encode into Vec");
    Any {
        type_url: type_url.to_string(),
        value: buf,
    }
}

fn build_http_listener_proto(
    sandbox_id: &SandboxId,
    allowed_hosts: &[String],
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
) -> envoy_types::pb::envoy::config::listener::v3::Listener {
    use envoy_types::pb::envoy::config::accesslog::v3::{access_log, AccessLog};
    use envoy_types::pb::envoy::config::cluster::v3::cluster::DnsLookupFamily;
    use envoy_types::pb::envoy::config::core::v3::{
        address, substitution_format_string, Address, Http1ProtocolOptions, Pipe,
        SubstitutionFormatString,
    };
    use envoy_types::pb::envoy::config::listener::v3::{filter, Filter, FilterChain, Listener};
    use envoy_types::pb::envoy::config::route::v3::RouteConfiguration;
    use envoy_types::pb::envoy::extensions::access_loggers::stream::v3::{
        stdout_access_log, StdoutAccessLog,
    };
    use envoy_types::pb::envoy::extensions::common::dynamic_forward_proxy::v3::DnsCacheConfig;
    use envoy_types::pb::envoy::extensions::filters::http::dynamic_forward_proxy::v3::{
        filter_config, FilterConfig,
    };
    use envoy_types::pb::envoy::extensions::filters::http::router::v3::Router;
    use envoy_types::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
        http_connection_manager, http_filter, HttpConnectionManager, HttpFilter,
    };

    let sandbox_uuid = sandbox_id.as_uuid();
    let dfp_filter = FilterConfig {
        implementation_specifier: Some(filter_config::ImplementationSpecifier::DnsCacheConfig(
            DnsCacheConfig {
                name: "dynamic_forward_proxy_cache".to_string(),
                dns_lookup_family: DnsLookupFamily::V4Only as i32,
                ..Default::default()
            },
        )),
        ..Default::default()
    };

    let hcm = HttpConnectionManager {
        stat_prefix: format!("{sandbox_uuid}_http"),
        http_protocol_options: Some(Http1ProtocolOptions {
            allow_absolute_url: Some(envoy_types::pb::google::protobuf::BoolValue { value: true }),
            ..Default::default()
        }),
        access_log: vec![AccessLog {
            name: "envoy.access_loggers.stdout".to_string(),
            config_type: Some(access_log::ConfigType::TypedConfig(pack_any(
                "type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog",
                &StdoutAccessLog {
                    access_log_format: Some(stdout_access_log::AccessLogFormat::LogFormat(
                        SubstitutionFormatString {
                            format: Some(substitution_format_string::Format::JsonFormat(
                                access_log_json_format(format!("{sandbox_uuid}_http")),
                            )),
                            ..Default::default()
                        },
                    )),
                },
            ))),
            ..Default::default()
        }],
        // Disable stream idle timeout so long-lived connections (SSE / streaming
        // LLM responses / MCP) are not killed by the default 5-minute idle limit.
        stream_idle_timeout: Some(envoy_types::pb::google::protobuf::Duration { seconds: 0, nanos: 0 }),
        upgrade_configs: vec![http_connection_manager::UpgradeConfig {
            upgrade_type: "CONNECT".to_string(),
            ..Default::default()
        }],
        route_specifier: Some(http_connection_manager::RouteSpecifier::RouteConfig(
            RouteConfiguration {
                virtual_hosts: build_virtual_hosts_proto(
                    allowed_hosts,
                    credentials,
                    proxy_auth_token,
                ),
                ..Default::default()
            },
        )),
        http_filters: vec![
            HttpFilter {
                name: "envoy.filters.http.dynamic_forward_proxy".to_string(),
                config_type: Some(http_filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig",
                    &dfp_filter,
                ))),
                ..Default::default()
            },
            HttpFilter {
                name: "envoy.filters.http.router".to_string(),
                config_type: Some(http_filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router",
                    &Router::default(),
                ))),
                ..Default::default()
            },
        ],
        ..Default::default()
    };

    Listener {
        name: format!("{sandbox_uuid}_http"),
        address: Some(Address {
            address: Some(address::Address::Pipe(Pipe {
                path: format!("/sockets/{sandbox_uuid}/http.sock"),
                // See the gRPC listener pipe above for why this is 0666 at
                // creation time. The HTTP proxy still requires the per-sandbox
                // proxy auth token before credential-bearing routes are usable.
                mode: 438,
            })),
        }),
        filter_chains: vec![FilterChain {
            filters: vec![Filter {
                name: "envoy.filters.network.http_connection_manager".to_string(),
                config_type: Some(filter::ConfigType::TypedConfig(pack_any(
                    "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
                    &hcm,
                ))),
            }],
            ..Default::default()
        }],
        ..Default::default()
    }
}

pub(crate) fn build_virtual_hosts_proto(
    allowed_hosts: &[String],
    credentials: &[EgressCredentialRoute],
    proxy_auth_token: Option<&str>,
) -> Vec<envoy_types::pb::envoy::config::route::v3::VirtualHost> {
    use envoy_types::pb::envoy::config::core::v3::{
        data_source, header_value_option, DataSource, HeaderValue, HeaderValueOption,
    };
    use envoy_types::pb::envoy::config::route::v3::{
        route, route_action, route_match, DirectResponseAction, Route, RouteAction, RouteMatch,
        VirtualHost,
    };

    let mut vhosts = Vec::new();

    // Credential-injection vhosts (mirror of build_virtual_hosts_json).
    for (match_host, routes) in group_credentials_by_host(credentials) {
        let proto_routes: Vec<Route> = routes
            .iter()
            .map(|r| {
                let headers: Vec<HeaderValueOption> = r
                    .inject_headers
                    .iter()
                    .map(|(k, v)| HeaderValueOption {
                        header: Some(HeaderValue {
                            key: k.clone(),
                            value: escape_envoy_header_value(v),
                            ..Default::default()
                        }),
                        append_action:
                            header_value_option::HeaderAppendAction::OverwriteIfExistsOrAdd as i32,
                        ..Default::default()
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
                let path_specifier = match &r.path_mapping {
                    EgressPathMapping::Passthrough {
                        matcher: EgressPathMatcher::Any,
                    } => route_match::PathSpecifier::Prefix("/".to_string()),
                    EgressPathMapping::Passthrough {
                        matcher: EgressPathMatcher::Exact(path),
                    }
                    | EgressPathMapping::RewriteExact {
                        exposed_path: path, ..
                    } => route_match::PathSpecifier::Path(path.clone()),
                    EgressPathMapping::Passthrough {
                        matcher: EgressPathMatcher::Prefix(prefix),
                    }
                    | EgressPathMapping::RewritePrefix {
                        exposed_prefix: prefix,
                        ..
                    } => route_match::PathSpecifier::Prefix(prefix.clone()),
                };
                let is_transparent = r.exposure == EgressExposure::Transparent;
                let prefix_rewrite = match &r.path_mapping {
                    EgressPathMapping::Passthrough { .. } => String::new(),
                    EgressPathMapping::RewriteExact { upstream_path, .. } => upstream_path.clone(),
                    EgressPathMapping::RewritePrefix {
                        upstream_prefix, ..
                    } => upstream_prefix.clone(),
                };
                let host_rewrite = if is_transparent {
                    None
                } else {
                    Some(route_action::HostRewriteSpecifier::HostRewriteLiteral(
                        upstream_authority(&r.upstream_host, r.upstream_port, r.upstream_tls),
                    ))
                };
                Route {
                    r#match: Some(RouteMatch {
                        path_specifier: Some(path_specifier),
                        headers: proxy_auth_headers_proto(proxy_auth_token),
                        ..Default::default()
                    }),
                    action: Some(route::Action::Route(RouteAction {
                        cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                            r.cluster_name.clone(),
                        )),
                        host_rewrite_specifier: host_rewrite,
                        prefix_rewrite,
                        // Disable the default 15s route timeout — streaming
                        // responses (LLM, SSE MCP) can run for minutes.
                        timeout: Some(envoy_types::pb::google::protobuf::Duration {
                            seconds: 0,
                            nanos: 0,
                        }),
                        retry_policy: match r.retry_mode {
                            EgressRetryMode::Disabled => None,
                            EgressRetryMode::SafeIdempotent => {
                                Some(envoy_types::pb::envoy::config::route::v3::RetryPolicy {
                                    retry_on: "5xx,reset,connect-failure".to_string(),
                                    num_retries: Some(
                                        envoy_types::pb::google::protobuf::UInt32Value { value: 2 },
                                    ),
                                    ..Default::default()
                                })
                            }
                        },
                        ..Default::default()
                    })),
                    request_headers_to_add: headers,
                    request_headers_to_remove: headers_to_remove,
                    ..Default::default()
                }
            })
            .collect();

        let mut domains = vec![
            match_host.clone(),
            format!("{match_host}:80"),
            format!("{match_host}:443"),
        ];
        for r in &routes {
            if r.upstream_port != 80 && r.upstream_port != 443 {
                let with_port = format!("{match_host}:{}", r.upstream_port);
                if !domains.contains(&with_port) {
                    domains.push(with_port);
                }
            }
        }

        vhosts.push(VirtualHost {
            name: format!("egress_{}", match_host.replace(['.', ':'], "_")),
            domains,
            routes: proto_routes,
            ..Default::default()
        });
    }

    if !allowed_hosts.is_empty() {
        let mut domains = Vec::new();
        for host in allowed_hosts {
            domains.push(host.clone());
            if !host.contains(':') {
                domains.push(format!("{host}:443"));
                domains.push(format!("{host}:80"));
            }
        }

        // CONNECT route → dynamic_forward_proxy with CONNECT upgrade.
        let connect_route = Route {
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::ConnectMatcher(
                    route_match::ConnectMatcher {},
                )),
                headers: proxy_auth_headers_proto(proxy_auth_token),
                ..Default::default()
            }),
            action: Some(route::Action::Route(RouteAction {
                cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                    "dynamic_forward_proxy".to_string(),
                )),
                upgrade_configs: vec![route_action::UpgradeConfig {
                    upgrade_type: "CONNECT".to_string(),
                    connect_config: Some(route_action::upgrade_config::ConnectConfig::default()),
                    ..Default::default()
                }],
                ..Default::default()
            })),
            request_headers_to_remove: vec!["proxy-authorization".to_string()],
            ..Default::default()
        };

        // Plain prefix "/" route → dynamic_forward_proxy.
        let prefix_route = Route {
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                headers: proxy_auth_headers_proto(proxy_auth_token),
                ..Default::default()
            }),
            action: Some(route::Action::Route(RouteAction {
                cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                    "dynamic_forward_proxy".to_string(),
                )),
                timeout: Some(envoy_types::pb::google::protobuf::Duration {
                    seconds: 0,
                    nanos: 0,
                }),
                retry_policy: Some(envoy_types::pb::envoy::config::route::v3::RetryPolicy {
                    retry_on: "5xx,reset,connect-failure".to_string(),
                    num_retries: Some(envoy_types::pb::google::protobuf::UInt32Value { value: 2 }),
                    ..Default::default()
                }),
                ..Default::default()
            })),
            request_headers_to_remove: vec!["proxy-authorization".to_string()],
            ..Default::default()
        };

        vhosts.push(VirtualHost {
            name: "allowed".to_string(),
            domains,
            routes: vec![connect_route, prefix_route],
            ..Default::default()
        });
    }

    // Catch-all: deny everything not explicitly allowed with a 403.
    vhosts.push(VirtualHost {
        name: "deny_all".to_string(),
        domains: vec!["*".to_string()],
        routes: vec![Route {
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                ..Default::default()
            }),
            action: Some(route::Action::DirectResponse(DirectResponseAction {
                status: 403,
                body: Some(DataSource {
                    specifier: Some(data_source::Specifier::InlineString(
                        "Host not in allowlist".to_string(),
                    )),
                    ..Default::default()
                }),
            })),
            ..Default::default()
        }],
        ..Default::default()
    });

    vhosts
}

fn proxy_auth_headers_proto(
    proxy_auth_token: Option<&str>,
) -> Vec<envoy_types::pb::envoy::config::route::v3::HeaderMatcher> {
    use envoy_types::pb::envoy::config::route::v3::{header_matcher, HeaderMatcher};
    use envoy_types::pb::envoy::r#type::matcher::v3::{string_matcher, StringMatcher};

    let Some(token) = proxy_auth_token.filter(|token| !token.is_empty()) else {
        return vec![];
    };
    vec![HeaderMatcher {
        name: "proxy-authorization".to_string(),
        header_match_specifier: Some(header_matcher::HeaderMatchSpecifier::StringMatch(
            StringMatcher {
                match_pattern: Some(string_matcher::MatchPattern::Exact(
                    proxy_authorization_value(token),
                )),
                ..Default::default()
            },
        )),
        ..Default::default()
    }]
}
