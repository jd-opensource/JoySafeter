use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::env;

use anyhow::Context;
use base64::Engine as _;
use envoy_types::pb::google::protobuf::Any;
use envoy_types_v076::pb::envoy::config::cluster::v3::{cluster, Cluster};
use envoy_types_v076::pb::envoy::config::core::v3::{
    address, config_source, data_source, grpc_service, socket_address, Address,
    AggregatedConfigSource, ConfigSource, DataSource, GrpcService, Http1ProtocolOptions,
    Http2ProtocolOptions, Pipe, SocketAddress, TransportSocket,
};
use envoy_types_v076::pb::envoy::config::endpoint::v3::{
    lb_endpoint, ClusterLoadAssignment, Endpoint, LbEndpoint, LocalityLbEndpoints,
};
use envoy_types_v076::pb::envoy::config::listener::v3::{filter, Filter, FilterChain, Listener};
use envoy_types_v076::pb::envoy::config::route::v3::{
    header_matcher, route, route_action, route_match, DirectResponseAction, HeaderMatcher, Route,
    RouteAction, RouteConfiguration, RouteMatch, VirtualHost,
};
use envoy_types_v076::pb::envoy::extensions::filters::http::ext_authz::v3::ExtAuthz;
use envoy_types_v076::pb::envoy::extensions::filters::http::router::v3::Router;
use envoy_types_v076::pb::envoy::extensions::filters::network::http_connection_manager::v3::{
    http_connection_manager, http_filter, HttpConnectionManager, HttpFilter, Rds,
};
use envoy_types_v076::pb::envoy::extensions::transport_sockets::tls::v3::{
    common_tls_context, subject_alt_name_matcher, CertificateValidationContext, CommonTlsContext,
    DownstreamTlsContext, SubjectAltNameMatcher, TlsCertificate, TlsParameters, UpstreamTlsContext,
};
use envoy_types_v076::pb::envoy::extensions::upstreams::http::v3::{
    http_protocol_options, HttpProtocolOptions,
};
use envoy_types_v076::pb::envoy::r#type::matcher::v3::{
    string_matcher, RegexMatchAndSubstitute, RegexMatcher, StringMatcher,
};
use envoy_types_v076::pb::google::protobuf::{Duration, UInt32Value};
use prost14::Message;
use sha2::{Digest, Sha256};

use super::policy::{self, CredentialRoute, SandboxPolicy, Upstream};
use super::snapshot::{CompiledSnapshot, CLUSTER_TYPE_URL, LISTENER_TYPE_URL, ROUTE_TYPE_URL};

const CREDENTIAL_ROUTES_NAME: &str = "joysafeter_credential_routes";
const FORWARD_ROUTES_NAME: &str = "joysafeter_forward_proxy_routes";
const DYNAMIC_FORWARD_CLUSTER: &str = "joysafeter_dynamic_forward_proxy";
const DYNAMIC_FORWARD_CACHE: &str = "joysafeter_dynamic_forward_proxy_cache";
const EXT_AUTHZ_FILTER: &str = "envoy.filters.http.ext_authz";

#[derive(Debug, Clone)]
pub struct CompilerConfig {
    pub credential_address: String,
    pub credential_port: u32,
    pub forward_address: String,
    pub forward_port: u32,
    pub authz_cluster: String,
    pub authz_host: String,
    pub authz_port: u32,
    pub authz_tls: bool,
    pub authz_server_name: String,
    pub authz_client_cert: String,
    pub authz_client_key: String,
    pub authz_ca: String,
    pub downstream_tls: bool,
    pub downstream_cert: String,
    pub downstream_key: String,
    pub public_ca: String,
    pub socket_root: String,
    pub orchestrator_grpc_cluster: String,
    pub denied_cidrs: Vec<String>,
}

impl Default for CompilerConfig {
    fn default() -> Self {
        Self {
            credential_address: "0.0.0.0".to_string(),
            credential_port: 8443,
            forward_address: "0.0.0.0".to_string(),
            forward_port: 8080,
            authz_cluster: "joysafeter_egress_authz".to_string(),
            authz_host: "joysafeter-egress-authz.joysafeter-control.svc.cluster.local".to_string(),
            authz_port: 18090,
            authz_tls: true,
            authz_server_name: "joysafeter-egress-authz.joysafeter-control.svc.cluster.local"
                .to_string(),
            authz_client_cert: "/var/run/joysafeter-egress/authz-tls/tls.crt".to_string(),
            authz_client_key: "/var/run/joysafeter-egress/authz-tls/tls.key".to_string(),
            authz_ca: "/var/run/joysafeter-egress/authz-tls/ca.crt".to_string(),
            downstream_tls: true,
            downstream_cert: "/var/run/joysafeter-egress/downstream-tls/tls.crt".to_string(),
            downstream_key: "/var/run/joysafeter-egress/downstream-tls/tls.key".to_string(),
            public_ca: "/etc/ssl/certs/ca-certificates.crt".to_string(),
            socket_root: "/sockets".to_string(),
            orchestrator_grpc_cluster: "orchestrator_grpc".to_string(),
            denied_cidrs: vec![
                "0.0.0.0/8",
                "10.0.0.0/8",
                "100.64.0.0/10",
                "127.0.0.0/8",
                "169.254.0.0/16",
                "172.16.0.0/12",
                "192.0.0.0/24",
                "192.0.2.0/24",
                "192.168.0.0/16",
                "198.18.0.0/15",
                "198.51.100.0/24",
                "203.0.113.0/24",
                "224.0.0.0/4",
                "240.0.0.0/4",
                "::/128",
                "::1/128",
                "2001:db8::/32",
                "fc00::/7",
                "fe80::/10",
                "ff00::/8",
            ]
            .into_iter()
            .map(str::to_string)
            .collect(),
        }
    }
}

impl CompilerConfig {
    pub fn from_env(denied_cidrs: Vec<String>) -> anyhow::Result<Self> {
        let defaults = Self::default();
        let config = Self {
            credential_address: env_string(
                "JOYSAFETER_EGRESS_CREDENTIAL_LISTENER_ADDR",
                defaults.credential_address,
            ),
            credential_port: env_u32(
                "JOYSAFETER_EGRESS_CREDENTIAL_LISTENER_PORT",
                defaults.credential_port,
            )?,
            forward_address: env_string(
                "JOYSAFETER_EGRESS_FORWARD_LISTENER_ADDR",
                defaults.forward_address,
            ),
            forward_port: env_u32(
                "JOYSAFETER_EGRESS_FORWARD_LISTENER_PORT",
                defaults.forward_port,
            )?,
            authz_cluster: defaults.authz_cluster,
            authz_host: env_string("JOYSAFETER_EGRESS_AUTHZ_HOST", defaults.authz_host),
            authz_port: env_u32("JOYSAFETER_EGRESS_AUTHZ_PORT", defaults.authz_port)?,
            authz_tls: env_bool("JOYSAFETER_EGRESS_AUTHZ_MTLS", defaults.authz_tls)?,
            authz_server_name: env_string(
                "JOYSAFETER_EGRESS_AUTHZ_SERVER_NAME",
                defaults.authz_server_name,
            ),
            authz_client_cert: env_string(
                "JOYSAFETER_EGRESS_AUTHZ_CLIENT_CERT",
                defaults.authz_client_cert,
            ),
            authz_client_key: env_string(
                "JOYSAFETER_EGRESS_AUTHZ_CLIENT_KEY",
                defaults.authz_client_key,
            ),
            authz_ca: env_string("JOYSAFETER_EGRESS_AUTHZ_CA", defaults.authz_ca),
            downstream_tls: env_bool("JOYSAFETER_EGRESS_DOWNSTREAM_TLS", defaults.downstream_tls)?,
            downstream_cert: env_string(
                "JOYSAFETER_EGRESS_DOWNSTREAM_CERT",
                defaults.downstream_cert,
            ),
            downstream_key: env_string("JOYSAFETER_EGRESS_DOWNSTREAM_KEY", defaults.downstream_key),
            public_ca: env_string("JOYSAFETER_EGRESS_PUBLIC_CA", defaults.public_ca),
            socket_root: env_string("JOYSAFETER_EGRESS_SOCKET_ROOT", defaults.socket_root),
            orchestrator_grpc_cluster: defaults.orchestrator_grpc_cluster,
            denied_cidrs,
        };
        validate_config(&config)?;
        Ok(config)
    }
}

fn env_string(name: &str, default: String) -> String {
    env::var(name)
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(default)
}

fn env_u32(name: &str, default: u32) -> anyhow::Result<u32> {
    let Some(raw) = env::var(name).ok().filter(|value| !value.trim().is_empty()) else {
        return Ok(default);
    };
    raw.parse::<u32>()
        .with_context(|| format!("{name} must be an unsigned 32-bit integer"))
}

fn env_bool(name: &str, default: bool) -> anyhow::Result<bool> {
    let Some(raw) = env::var(name).ok().filter(|value| !value.trim().is_empty()) else {
        return Ok(default);
    };
    match raw.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "t" | "yes" | "y" | "on" => Ok(true),
        "0" | "false" | "f" | "no" | "n" | "off" => Ok(false),
        _ => anyhow::bail!("{name} must be a boolean"),
    }
}

#[derive(Debug, Clone)]
pub struct CompileInput<'a> {
    pub snapshot_group_key: &'a str,
    pub source_group_key: &'a str,
    pub generation: i64,
    pub content_sha256: &'a str,
    pub policy_schema_version: i32,
    pub desired_policies: &'a [u8],
}

pub fn compile_kubernetes(
    config: &CompilerConfig,
    input: CompileInput<'_>,
) -> anyhow::Result<CompiledSnapshot> {
    compile_for_provider(config, "k8s", input)
}

pub fn compile_for_provider(
    config: &CompilerConfig,
    provider: &str,
    input: CompileInput<'_>,
) -> anyhow::Result<CompiledSnapshot> {
    validate_config(config)?;
    let policies = policy::decode(input.policy_schema_version, input.desired_policies)?;
    let denied_cidrs = merged_denied_cidrs(config, &policies)?;

    let mut resources = BTreeMap::<String, BTreeMap<String, Any>>::new();
    for cluster in build_clusters(config, &policies, &denied_cidrs)? {
        insert_resource(&mut resources, CLUSTER_TYPE_URL, &cluster.name, &cluster)?;
    }
    let (routes, listeners) = match provider {
        "k8s" | "kubernetes" => (
            build_routes(&policies, input.source_group_key, input.generation)?,
            build_listeners(config, &denied_cidrs)?,
        ),
        "docker" => build_docker_resources(
            config,
            &policies,
            &denied_cidrs,
            input.source_group_key,
            input.generation,
        )?,
        other => anyhow::bail!("unsupported egress provider {other:?}"),
    };
    for route in routes {
        insert_resource(&mut resources, ROUTE_TYPE_URL, &route.name, &route)?;
    }
    for listener in listeners {
        insert_resource(&mut resources, LISTENER_TYPE_URL, &listener.name, &listener)?;
    }

    CompiledSnapshot::new(
        input.snapshot_group_key,
        input.generation,
        input.content_sha256,
        resources,
    )
}

fn validate_config(config: &CompilerConfig) -> anyhow::Result<()> {
    anyhow::ensure!(
        !config.credential_address.trim().is_empty() && config.credential_port > 0,
        "credential listener address and port are required"
    );
    anyhow::ensure!(
        !config.forward_address.trim().is_empty() && config.forward_port > 0,
        "forward listener address and port are required"
    );
    anyhow::ensure!(
        config.credential_address != config.forward_address
            || config.credential_port != config.forward_port,
        "credential and forward listeners must differ"
    );
    anyhow::ensure!(
        !config.authz_cluster.trim().is_empty()
            && !config.authz_host.trim().is_empty()
            && config.authz_port > 0,
        "ext_authz cluster, host, and port are required"
    );
    if config.authz_tls {
        anyhow::ensure!(
            !config.authz_server_name.trim().is_empty()
                && !config.authz_client_cert.trim().is_empty()
                && !config.authz_client_key.trim().is_empty()
                && !config.authz_ca.trim().is_empty(),
            "ext_authz mTLS requires server name, client certificate, key, and CA"
        );
    }
    if config.downstream_tls {
        anyhow::ensure!(
            !config.downstream_cert.trim().is_empty() && !config.downstream_key.trim().is_empty(),
            "downstream TLS requires certificate and key"
        );
    }
    anyhow::ensure!(
        !config.public_ca.trim().is_empty(),
        "public CA path is required"
    );
    anyhow::ensure!(
        config.socket_root.starts_with('/'),
        "Docker socket root must be absolute"
    );
    anyhow::ensure!(
        !config.orchestrator_grpc_cluster.trim().is_empty(),
        "orchestrator gRPC cluster is required"
    );
    Ok(())
}

fn merged_denied_cidrs(
    config: &CompilerConfig,
    policies: &[SandboxPolicy],
) -> anyhow::Result<Vec<ModernCidrRange>> {
    let mut values = BTreeSet::new();
    for cidr in &config.denied_cidrs {
        values.insert(
            policy::normalize_cidr(cidr).map_err(|error| {
                anyhow::anyhow!("invalid compiler denied CIDR {cidr:?}: {error}")
            })?,
        );
    }
    for item in policies {
        values.extend(item.denied_cidrs.iter().cloned());
    }
    values
        .into_iter()
        .map(|cidr| modern_cidr_range(&cidr))
        .collect()
}

fn modern_cidr_range(cidr: &str) -> anyhow::Result<ModernCidrRange> {
    let (address_prefix, prefix_len) = cidr
        .split_once('/')
        .ok_or_else(|| anyhow::anyhow!("invalid normalized CIDR {cidr:?}"))?;
    Ok(ModernCidrRange {
        address_prefix: address_prefix.to_string(),
        prefix_len: Some(UInt32Value {
            value: prefix_len.parse()?,
        }),
    })
}

fn build_clusters(
    config: &CompilerConfig,
    policies: &[SandboxPolicy],
    denied_cidrs: &[ModernCidrRange],
) -> anyhow::Result<Vec<Cluster>> {
    let mut clusters = vec![
        authz_cluster(config),
        dynamic_forward_proxy_cluster(denied_cidrs)?,
    ];
    let mut upstreams = BTreeMap::new();
    for policy in policies {
        for route in &policy.credential_routes {
            upstreams
                .entry(upstream_cluster_name(&route.upstream))
                .or_insert_with(|| route.upstream.clone());
        }
    }
    for (name, upstream) in upstreams {
        clusters.push(upstream_cluster(config, &name, &upstream));
    }
    Ok(clusters)
}

fn strict_dns_cluster(name: &str, host: &str, port: u32) -> Cluster {
    Cluster {
        name: name.to_string(),
        connect_timeout: Some(duration(5)),
        lb_policy: cluster::LbPolicy::RoundRobin as i32,
        load_assignment: Some(ClusterLoadAssignment {
            cluster_name: name.to_string(),
            endpoints: vec![LocalityLbEndpoints {
                lb_endpoints: vec![LbEndpoint {
                    host_identifier: Some(lb_endpoint::HostIdentifier::Endpoint(Endpoint {
                        address: Some(socket_address_value(host, port)),
                        ..Default::default()
                    })),
                    ..Default::default()
                }],
                ..Default::default()
            }],
            ..Default::default()
        }),
        cluster_discovery_type: Some(cluster::ClusterDiscoveryType::Type(
            cluster::DiscoveryType::StrictDns as i32,
        )),
        ..Default::default()
    }
}

fn authz_cluster(config: &CompilerConfig) -> Cluster {
    let mut cluster =
        strict_dns_cluster(&config.authz_cluster, &config.authz_host, config.authz_port);
    set_http_protocol(&mut cluster, "http2", true);
    if config.authz_tls {
        cluster.transport_socket = Some(tls_transport_socket(
            "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
            &UpstreamTlsContext {
                sni: config.authz_server_name.clone(),
                common_tls_context: Some(CommonTlsContext {
                    tls_certificates: vec![tls_certificate(
                        &config.authz_client_cert,
                        &config.authz_client_key,
                    )],
                    validation_context_type: Some(
                        common_tls_context::ValidationContextType::ValidationContext(
                            validation_context(&config.authz_ca, &config.authz_server_name),
                        ),
                    ),
                    alpn_protocols: vec!["h2".to_string()],
                    ..Default::default()
                }),
                ..Default::default()
            },
        ));
    }
    cluster
}

fn upstream_cluster(config: &CompilerConfig, name: &str, upstream: &Upstream) -> Cluster {
    let mut cluster = strict_dns_cluster(name, &upstream.host, u32::from(upstream.port));
    set_http_protocol(&mut cluster, &upstream.protocol, upstream.scheme == "https");
    if upstream.scheme == "https" {
        cluster.transport_socket = Some(tls_transport_socket(
            "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.UpstreamTlsContext",
            &UpstreamTlsContext {
                sni: upstream.host.clone(),
                common_tls_context: Some(CommonTlsContext {
                    validation_context_type: Some(
                        common_tls_context::ValidationContextType::ValidationContext(
                            validation_context(&config.public_ca, &upstream.host),
                        ),
                    ),
                    alpn_protocols: if upstream.protocol == "http1" {
                        Vec::new()
                    } else {
                        vec!["h2".to_string(), "http/1.1".to_string()]
                    },
                    ..Default::default()
                }),
                ..Default::default()
            },
        ));
    }
    cluster
}

fn set_http_protocol(cluster: &mut Cluster, protocol: &str, tls: bool) {
    let protocol = if protocol == "auto" && !tls {
        "http1"
    } else {
        protocol
    };
    let upstream_protocol_options = match protocol {
        "auto" => http_protocol_options::UpstreamProtocolOptions::AutoConfig(
            http_protocol_options::AutoHttpConfig {
                http_protocol_options: Some(Http1ProtocolOptions::default()),
                http2_protocol_options: Some(Http2ProtocolOptions::default()),
                ..Default::default()
            },
        ),
        "http2" => http_protocol_options::UpstreamProtocolOptions::ExplicitHttpConfig(
            http_protocol_options::ExplicitHttpConfig {
                protocol_config: Some(
                    http_protocol_options::explicit_http_config::ProtocolConfig::Http2ProtocolOptions(
                        Http2ProtocolOptions::default(),
                    ),
                ),
            },
        ),
        _ => http_protocol_options::UpstreamProtocolOptions::ExplicitHttpConfig(
            http_protocol_options::ExplicitHttpConfig {
                protocol_config: Some(
                    http_protocol_options::explicit_http_config::ProtocolConfig::HttpProtocolOptions(
                        Http1ProtocolOptions::default(),
                    ),
                ),
            },
        ),
    };
    cluster.typed_extension_protocol_options.insert(
        "envoy.extensions.upstreams.http.v3.HttpProtocolOptions".to_string(),
        pack_new(
            "type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions",
            &HttpProtocolOptions {
                upstream_protocol_options: Some(upstream_protocol_options),
                ..Default::default()
            },
        ),
    );
}

fn dynamic_forward_proxy_cluster(denied_cidrs: &[ModernCidrRange]) -> anyhow::Result<Cluster> {
    let config = ModernDynamicForwardProxyClusterConfig {
        dns_cache_config: Some(dynamic_dns_cache(denied_cidrs)),
        allow_insecure_cluster_options: false,
        allow_coalesced_connections: false,
    };
    Ok(Cluster {
        name: DYNAMIC_FORWARD_CLUSTER.to_string(),
        connect_timeout: Some(duration(5)),
        lb_policy: cluster::LbPolicy::ClusterProvided as i32,
        cluster_discovery_type: Some(cluster::ClusterDiscoveryType::ClusterType(
            cluster::CustomClusterType {
                name: "envoy.clusters.dynamic_forward_proxy".to_string(),
                typed_config: Some(pack_new(
                    "type.googleapis.com/envoy.extensions.clusters.dynamic_forward_proxy.v3.ClusterConfig",
                    &config,
                )),
            },
        )),
        ..Default::default()
    })
}

fn dynamic_dns_cache(denied_cidrs: &[ModernCidrRange]) -> ModernDnsCacheConfig {
    ModernDnsCacheConfig {
        name: DYNAMIC_FORWARD_CACHE.to_string(),
        dns_lookup_family: cluster::DnsLookupFamily::V4Preferred as i32,
        dns_refresh_rate: Some(duration(30)),
        host_ttl: Some(duration(300)),
        max_hosts: Some(UInt32Value { value: 8192 }),
        resolved_address_filter: Some(ModernAddressMatcher {
            ranges: denied_cidrs.to_vec(),
            invert_match: false,
        }),
    }
}

fn build_routes(
    policies: &[SandboxPolicy],
    group_key: &str,
    generation: i64,
) -> anyhow::Result<Vec<RouteConfiguration>> {
    Ok(vec![
        credential_routes(policies, group_key, generation)?,
        forward_routes(),
    ])
}

fn credential_routes(
    policies: &[SandboxPolicy],
    group_key: &str,
    generation: i64,
) -> anyhow::Result<RouteConfiguration> {
    let mut routes = Vec::new();
    for policy in policies {
        for credential in &policy.credential_routes {
            let path = join_route_path(
                &synthetic_route_base(&policy.sandbox_id, &credential.consumer_route_id),
                &credential.match_path.value,
            );
            for method in &credential.methods {
                routes.push(credential_route(
                    &policy.sandbox_id,
                    credential,
                    &path,
                    method,
                    group_key,
                    generation,
                )?);
            }
        }
    }
    routes.sort_by(|left, right| {
        route_path_len(right)
            .cmp(&route_path_len(left))
            .then_with(|| left.name.cmp(&right.name))
    });
    routes.push(deny_route("credential route not found"));
    Ok(RouteConfiguration {
        name: CREDENTIAL_ROUTES_NAME.to_string(),
        virtual_hosts: vec![VirtualHost {
            name: "credential".to_string(),
            domains: vec!["*".to_string()],
            routes,
            ..Default::default()
        }],
        ..Default::default()
    })
}

fn credential_route(
    sandbox_id: &str,
    credential: &CredentialRoute,
    path: &str,
    method: &str,
    group_key: &str,
    generation: i64,
) -> anyhow::Result<Route> {
    let path_specifier = if credential.match_path.kind == "exact" {
        route_match::PathSpecifier::Path(path.to_string())
    } else {
        route_match::PathSpecifier::Prefix(path.to_string())
    };
    let mut context_extensions = BTreeMap::new();
    context_extensions.insert(
        "joysafeter_traffic_class".to_string(),
        "credential".to_string(),
    );
    context_extensions.insert("joysafeter_sandbox_id".to_string(), sandbox_id.to_string());
    context_extensions.insert(
        "joysafeter_route_id".to_string(),
        credential.route_id.clone(),
    );
    context_extensions.insert("joysafeter_group_key".to_string(), group_key.to_string());
    context_extensions.insert(
        "joysafeter_policy_generation".to_string(),
        generation.to_string(),
    );

    let typed_per_filter_config = ext_authz_context(context_extensions);

    let exact_rewrite = (credential.match_path.kind == "exact").then(|| RegexMatchAndSubstitute {
        pattern: Some(RegexMatcher {
            regex: format!("^{}$", regex_escape(path)),
            ..Default::default()
        }),
        substitution: credential.upstream.base_path.clone(),
    });

    Ok(Route {
        name: format!(
            "credential_{}_{}_{}",
            sandbox_id.replace('-', "_"),
            safe_name(&credential.route_id),
            method.to_ascii_lowercase()
        ),
        r#match: Some(RouteMatch {
            headers: vec![HeaderMatcher {
                name: ":method".to_string(),
                header_match_specifier: Some(header_matcher::HeaderMatchSpecifier::StringMatch(
                    StringMatcher {
                        match_pattern: Some(string_matcher::MatchPattern::Exact(
                            method.to_string(),
                        )),
                        ..Default::default()
                    },
                )),
                ..Default::default()
            }],
            path_specifier: Some(path_specifier),
            ..Default::default()
        }),
        typed_per_filter_config,
        request_headers_to_remove: sensitive_headers_except(
            &credential.remove_headers,
            &credential.inject_header,
        ),
        action: Some(route::Action::Route(RouteAction {
            prefix_rewrite: if credential.match_path.kind == "prefix" {
                credential.upstream.base_path.clone()
            } else {
                String::new()
            },
            regex_rewrite: exact_rewrite,
            timeout: Some(timeout_for(&credential.timeout_profile)),
            upgrade_configs: if credential.websocket {
                vec![route_action::UpgradeConfig {
                    upgrade_type: "websocket".to_string(),
                    enabled: Some(envoy_types_v076::pb::google::protobuf::BoolValue {
                        value: true,
                    }),
                    ..Default::default()
                }]
            } else {
                Vec::new()
            },
            cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                upstream_cluster_name(&credential.upstream),
            )),
            host_rewrite_specifier: Some(route_action::HostRewriteSpecifier::HostRewriteLiteral(
                credential.upstream.host.clone(),
            )),
            ..Default::default()
        })),
        ..Default::default()
    })
}

fn forward_routes() -> RouteConfiguration {
    let typed_per_filter_config = ext_authz_context(BTreeMap::from([(
        "joysafeter_traffic_class".to_string(),
        "forward_proxy".to_string(),
    )]));
    RouteConfiguration {
        name: FORWARD_ROUTES_NAME.to_string(),
        virtual_hosts: vec![VirtualHost {
            name: "forward_proxy".to_string(),
            domains: vec!["*".to_string()],
            routes: vec![
                Route {
                    name: "forward_connect".to_string(),
                    r#match: Some(RouteMatch {
                        path_specifier: Some(route_match::PathSpecifier::ConnectMatcher(
                            route_match::ConnectMatcher {},
                        )),
                        ..Default::default()
                    }),
                    typed_per_filter_config: typed_per_filter_config.clone(),
                    request_headers_to_remove: vec![
                        "proxy-authorization".to_string(),
                        "x-joysafeter-sandbox-id".to_string(),
                        "x-joysafeter-route-id".to_string(),
                    ],
                    action: Some(route::Action::Route(RouteAction {
                        cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                            DYNAMIC_FORWARD_CLUSTER.to_string(),
                        )),
                        upgrade_configs: vec![route_action::UpgradeConfig {
                            upgrade_type: "CONNECT".to_string(),
                            connect_config: Some(
                                route_action::upgrade_config::ConnectConfig::default(),
                            ),
                            ..Default::default()
                        }],
                        ..Default::default()
                    })),
                    ..Default::default()
                },
                Route {
                    name: "forward_http".to_string(),
                    r#match: Some(RouteMatch {
                        path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                        ..Default::default()
                    }),
                    typed_per_filter_config,
                    request_headers_to_remove: vec![
                        "proxy-authorization".to_string(),
                        "x-joysafeter-sandbox-id".to_string(),
                        "x-joysafeter-route-id".to_string(),
                    ],
                    action: Some(route::Action::Route(RouteAction {
                        timeout: Some(duration(0)),
                        cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                            DYNAMIC_FORWARD_CLUSTER.to_string(),
                        )),
                        ..Default::default()
                    })),
                    ..Default::default()
                },
            ],
            ..Default::default()
        }],
        ..Default::default()
    }
}

fn build_docker_resources(
    config: &CompilerConfig,
    policies: &[SandboxPolicy],
    denied_cidrs: &[ModernCidrRange],
    group_key: &str,
    generation: i64,
) -> anyhow::Result<(Vec<RouteConfiguration>, Vec<Listener>)> {
    let mut routes = Vec::with_capacity(policies.len() * 2);
    let mut listeners = Vec::with_capacity(policies.len() * 2);
    for policy in policies {
        let resource_id = policy.sandbox_id.replace('-', "_");
        let route_name = format!("joysafeter_routes_{resource_id}");
        routes.push(docker_routes(policy, &route_name, group_key, generation)?);
        listeners.push(pipe_listener(
            &format!("joysafeter_{resource_id}_http"),
            &format!(
                "{}/{}/http.sock",
                config.socket_root.trim_end_matches('/'),
                policy.sandbox_id
            ),
            &route_name,
            Some(&config.authz_cluster),
            true,
            denied_cidrs,
        ));

        let control_route_name = format!("joysafeter_control_{resource_id}");
        routes.push(docker_control_routes(
            &control_route_name,
            &config.orchestrator_grpc_cluster,
        ));
        listeners.push(pipe_listener(
            &format!("joysafeter_{resource_id}_grpc"),
            &format!(
                "{}/{}/grpc.sock",
                config.socket_root.trim_end_matches('/'),
                policy.sandbox_id
            ),
            &control_route_name,
            None,
            false,
            denied_cidrs,
        ));
    }
    Ok((routes, listeners))
}

fn docker_routes(
    policy: &SandboxPolicy,
    name: &str,
    group_key: &str,
    generation: i64,
) -> anyhow::Result<RouteConfiguration> {
    let allowed = policy
        .allowed_public_hosts
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let mut by_host = BTreeMap::<&str, Vec<&CredentialRoute>>::new();
    for credential in &policy.credential_routes {
        by_host
            .entry(credential.match_authority.as_str())
            .or_default()
            .push(credential);
    }

    let mut virtual_hosts = Vec::with_capacity(by_host.len() + 2);
    for (host, mut credentials) in by_host {
        credentials.sort_by(|left, right| {
            right
                .match_path
                .value
                .len()
                .cmp(&left.match_path.value.len())
                .then_with(|| left.route_id.cmp(&right.route_id))
        });
        let mut host_routes = Vec::new();
        for credential in credentials {
            for method in &credential.methods {
                host_routes.push(credential_route(
                    &policy.sandbox_id,
                    credential,
                    &credential.match_path.value,
                    method,
                    group_key,
                    generation,
                )?);
            }
        }
        if policy.mode == "unrestricted" || host_allowed(host, &allowed) {
            host_routes.extend(plain_forward_routes());
        } else {
            host_routes.push(deny_route("path not authorized"));
        }
        virtual_hosts.push(VirtualHost {
            name: format!("credential_{}", safe_name(host)),
            domains: host_domains(host),
            routes: host_routes,
            ..Default::default()
        });
    }

    if policy.mode == "limited" && !policy.allowed_public_hosts.is_empty() {
        let mut domains = Vec::new();
        for host in &policy.allowed_public_hosts {
            domains.push(host.clone());
            if !host.starts_with("*.") {
                domains.push(format!("{host}:80"));
                domains.push(format!("{host}:443"));
            }
        }
        virtual_hosts.push(VirtualHost {
            name: "allowed".to_string(),
            domains,
            routes: plain_forward_routes(),
            typed_per_filter_config: ext_authz_disabled(),
            ..Default::default()
        });
    }

    virtual_hosts.push(if policy.mode == "unrestricted" {
        VirtualHost {
            name: "unrestricted".to_string(),
            domains: vec!["*".to_string()],
            routes: plain_forward_routes(),
            typed_per_filter_config: ext_authz_disabled(),
            ..Default::default()
        }
    } else {
        VirtualHost {
            name: "deny_all".to_string(),
            domains: vec!["*".to_string()],
            routes: vec![deny_route("host not authorized")],
            typed_per_filter_config: ext_authz_disabled(),
            ..Default::default()
        }
    });

    Ok(RouteConfiguration {
        name: name.to_string(),
        virtual_hosts,
        ..Default::default()
    })
}

fn docker_control_routes(name: &str, cluster: &str) -> RouteConfiguration {
    RouteConfiguration {
        name: name.to_string(),
        virtual_hosts: vec![VirtualHost {
            name: "control".to_string(),
            domains: vec!["*".to_string()],
            routes: vec![Route {
                name: "control_grpc".to_string(),
                r#match: Some(RouteMatch {
                    path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                    ..Default::default()
                }),
                action: Some(route::Action::Route(RouteAction {
                    timeout: Some(duration(0)),
                    cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                        cluster.to_string(),
                    )),
                    ..Default::default()
                })),
                ..Default::default()
            }],
            ..Default::default()
        }],
        ..Default::default()
    }
}

fn plain_forward_routes() -> Vec<Route> {
    vec![
        Route {
            name: "connect".to_string(),
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::ConnectMatcher(
                    route_match::ConnectMatcher {},
                )),
                ..Default::default()
            }),
            typed_per_filter_config: ext_authz_disabled(),
            action: Some(route::Action::Route(RouteAction {
                cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                    DYNAMIC_FORWARD_CLUSTER.to_string(),
                )),
                upgrade_configs: vec![route_action::UpgradeConfig {
                    upgrade_type: "CONNECT".to_string(),
                    connect_config: Some(route_action::upgrade_config::ConnectConfig::default()),
                    ..Default::default()
                }],
                ..Default::default()
            })),
            ..Default::default()
        },
        Route {
            name: "http".to_string(),
            r#match: Some(RouteMatch {
                path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
                ..Default::default()
            }),
            typed_per_filter_config: ext_authz_disabled(),
            action: Some(route::Action::Route(RouteAction {
                timeout: Some(duration(0)),
                cluster_specifier: Some(route_action::ClusterSpecifier::Cluster(
                    DYNAMIC_FORWARD_CLUSTER.to_string(),
                )),
                ..Default::default()
            })),
            ..Default::default()
        },
    ]
}

fn host_domains(host: &str) -> Vec<String> {
    vec![
        host.to_string(),
        format!("{host}:80"),
        format!("{host}:443"),
    ]
}

fn host_allowed(host: &str, allowed: &BTreeSet<&str>) -> bool {
    allowed.contains(host)
        || allowed
            .iter()
            .any(|pattern| pattern.starts_with("*.") && host.ends_with(&pattern[1..]))
}

fn deny_route(message: &str) -> Route {
    let typed_per_filter_config = ext_authz_disabled();
    Route {
        name: "deny".to_string(),
        r#match: Some(RouteMatch {
            path_specifier: Some(route_match::PathSpecifier::Prefix("/".to_string())),
            ..Default::default()
        }),
        typed_per_filter_config,
        action: Some(route::Action::DirectResponse(DirectResponseAction {
            status: 403,
            body: Some(envoy_types_v076::pb::envoy::config::core::v3::DataSource {
                specifier: Some(
                    envoy_types_v076::pb::envoy::config::core::v3::data_source::Specifier::InlineString(
                        message.to_string(),
                    ),
                ),
                ..Default::default()
            }),
            ..Default::default()
        })),
        ..Default::default()
    }
}

fn build_listeners(
    config: &CompilerConfig,
    denied_cidrs: &[ModernCidrRange],
) -> anyhow::Result<Vec<Listener>> {
    Ok(vec![
        http_listener(
            config,
            "joysafeter_credential_listener",
            &config.credential_address,
            config.credential_port,
            CREDENTIAL_ROUTES_NAME,
            false,
            &config.authz_cluster,
            denied_cidrs,
        )?,
        http_listener(
            config,
            "joysafeter_forward_proxy_listener",
            &config.forward_address,
            config.forward_port,
            FORWARD_ROUTES_NAME,
            true,
            &config.authz_cluster,
            denied_cidrs,
        )?,
    ])
}

fn ext_authz_http_filter(authz_cluster: &str) -> HttpFilter {
    HttpFilter {
        name: EXT_AUTHZ_FILTER.to_string(),
        config_type: Some(http_filter::ConfigType::TypedConfig(pack_new(
            "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthz",
            &ExtAuthz {
                transport_api_version:
                    envoy_types_v076::pb::envoy::config::core::v3::ApiVersion::V3 as i32,
                failure_mode_allow: false,
                services: Some(
                    envoy_types_v076::pb::envoy::extensions::filters::http::ext_authz::v3::ext_authz::Services::GrpcService(
                        GrpcService {
                            target_specifier: Some(grpc_service::TargetSpecifier::EnvoyGrpc(
                                grpc_service::EnvoyGrpc {
                                    cluster_name: authz_cluster.to_string(),
                                    ..Default::default()
                                },
                            )),
                            timeout: Some(duration(2)),
                            ..Default::default()
                        },
                    ),
                ),
                ..Default::default()
            },
        ))),
        ..Default::default()
    }
}

/// Builds the HTTP connection manager shared by every egress listener. `authz_cluster`
/// gates the ext_authz filter (the docker gRPC-control listener runs without it).
fn build_hcm(
    name: &str,
    route_name: &str,
    authz_cluster: Option<&str>,
    dynamic_forward: bool,
    denied_cidrs: &[ModernCidrRange],
) -> HttpConnectionManager {
    let mut filters = Vec::new();
    if let Some(authz_cluster) = authz_cluster {
        filters.push(ext_authz_http_filter(authz_cluster));
    }
    if dynamic_forward {
        filters.push(HttpFilter {
            name: "envoy.filters.http.dynamic_forward_proxy".to_string(),
            config_type: Some(http_filter::ConfigType::TypedConfig(pack_new(
                "type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig",
                &ModernDynamicForwardProxyFilterConfig {
                    dns_cache_config: Some(dynamic_dns_cache(denied_cidrs)),
                    save_upstream_address: false,
                },
            ))),
            ..Default::default()
        });
    }
    filters.push(HttpFilter {
        name: "envoy.filters.http.router".to_string(),
        config_type: Some(http_filter::ConfigType::TypedConfig(pack_new(
            "type.googleapis.com/envoy.extensions.filters.http.router.v3.Router",
            &Router::default(),
        ))),
        ..Default::default()
    });

    HttpConnectionManager {
        stat_prefix: name.to_string(),
        http_filters: filters,
        route_specifier: Some(http_connection_manager::RouteSpecifier::Rds(Rds {
            config_source: Some(ConfigSource {
                resource_api_version: envoy_types_v076::pb::envoy::config::core::v3::ApiVersion::V3
                    as i32,
                config_source_specifier: Some(config_source::ConfigSourceSpecifier::Ads(
                    AggregatedConfigSource {},
                )),
                ..Default::default()
            }),
            route_config_name: route_name.to_string(),
        })),
        stream_idle_timeout: Some(duration(0)),
        request_timeout: Some(duration(0)),
        use_remote_address: Some(envoy_types_v076::pb::google::protobuf::BoolValue { value: true }),
        upgrade_configs: if dynamic_forward {
            vec![
                http_connection_manager::UpgradeConfig {
                    upgrade_type: "CONNECT".to_string(),
                    ..Default::default()
                },
                http_connection_manager::UpgradeConfig {
                    upgrade_type: "websocket".to_string(),
                    ..Default::default()
                },
            ]
        } else {
            vec![http_connection_manager::UpgradeConfig {
                upgrade_type: "websocket".to_string(),
                ..Default::default()
            }]
        },
        ..Default::default()
    }
}

fn hcm_network_filter(hcm: &HttpConnectionManager) -> Filter {
    Filter {
        name: "envoy.filters.network.http_connection_manager".to_string(),
        config_type: Some(filter::ConfigType::TypedConfig(pack_new(
            "type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager",
            hcm,
        ))),
    }
}

fn http_listener(
    config: &CompilerConfig,
    name: &str,
    address_value: &str,
    port: u32,
    route_name: &str,
    dynamic_forward: bool,
    authz_cluster: &str,
    denied_cidrs: &[ModernCidrRange],
) -> anyhow::Result<Listener> {
    let hcm = build_hcm(
        name,
        route_name,
        Some(authz_cluster),
        dynamic_forward,
        denied_cidrs,
    );
    Ok(Listener {
        name: name.to_string(),
        address: Some(socket_address_value(address_value, port)),
        per_connection_buffer_limit_bytes: Some(UInt32Value { value: 1 << 20 }),
        filter_chains: vec![FilterChain {
            filters: vec![hcm_network_filter(&hcm)],
            transport_socket: if config.downstream_tls {
                Some(tls_transport_socket(
                    "type.googleapis.com/envoy.extensions.transport_sockets.tls.v3.DownstreamTlsContext",
                    &DownstreamTlsContext {
                        common_tls_context: Some(CommonTlsContext {
                            tls_params: Some(TlsParameters {
                                tls_minimum_protocol_version:
                                    envoy_types_v076::pb::envoy::extensions::transport_sockets::tls::v3::tls_parameters::TlsProtocol::TlSv12
                                        as i32,
                                ..Default::default()
                            }),
                            tls_certificates: vec![tls_certificate(
                                &config.downstream_cert,
                                &config.downstream_key,
                            )],
                            ..Default::default()
                        }),
                        ..Default::default()
                    },
                ))
            } else {
                None
            },
            ..Default::default()
        }],
        ..Default::default()
    })
}

fn pipe_listener(
    name: &str,
    path: &str,
    route_name: &str,
    authz_cluster: Option<&str>,
    dynamic_forward: bool,
    denied_cidrs: &[ModernCidrRange],
) -> Listener {
    let hcm = build_hcm(name, route_name, authz_cluster, dynamic_forward, denied_cidrs);
    Listener {
        name: name.to_string(),
        address: Some(Address {
            address: Some(address::Address::Pipe(Pipe {
                path: path.to_string(),
                mode: 438,
            })),
        }),
        per_connection_buffer_limit_bytes: Some(UInt32Value { value: 1 << 20 }),
        filter_chains: vec![FilterChain {
            filters: vec![hcm_network_filter(&hcm)],
            ..Default::default()
        }],
        ..Default::default()
    }
}

fn tls_transport_socket<M: Message>(type_url: &str, context: &M) -> TransportSocket {
    TransportSocket {
        name: "envoy.transport_sockets.tls".to_string(),
        config_type: Some(
            envoy_types_v076::pb::envoy::config::core::v3::transport_socket::ConfigType::TypedConfig(
                pack_new(type_url, context),
            ),
        ),
    }
}

fn tls_certificate(certificate: &str, private_key: &str) -> TlsCertificate {
    TlsCertificate {
        certificate_chain: Some(filename_source(certificate)),
        private_key: Some(filename_source(private_key)),
        ..Default::default()
    }
}

fn validation_context(ca_path: &str, server_name: &str) -> CertificateValidationContext {
    CertificateValidationContext {
        trusted_ca: Some(filename_source(ca_path)),
        match_typed_subject_alt_names: vec![SubjectAltNameMatcher {
            san_type: subject_alt_name_matcher::SanType::Dns as i32,
            matcher: Some(StringMatcher {
                match_pattern: Some(string_matcher::MatchPattern::Exact(server_name.to_string())),
                ..Default::default()
            }),
            ..Default::default()
        }],
        ..Default::default()
    }
}

fn filename_source(path: &str) -> DataSource {
    DataSource {
        specifier: Some(data_source::Specifier::Filename(path.to_string())),
        ..Default::default()
    }
}

fn socket_address_value(host: &str, port: u32) -> Address {
    Address {
        address: Some(address::Address::SocketAddress(SocketAddress {
            protocol: socket_address::Protocol::Tcp as i32,
            address: host.to_string(),
            port_specifier: Some(socket_address::PortSpecifier::PortValue(port)),
            ..Default::default()
        })),
    }
}

fn insert_resource<M: Message>(
    resources: &mut BTreeMap<String, BTreeMap<String, Any>>,
    type_url: &str,
    name: &str,
    message: &M,
) -> anyhow::Result<()> {
    anyhow::ensure!(!name.trim().is_empty(), "xDS resource name is required");
    let typed = resources.entry(type_url.to_string()).or_default();
    anyhow::ensure!(!typed.contains_key(name), "duplicate xDS resource {name:?}");
    typed.insert(
        name.to_string(),
        Any {
            type_url: type_url.to_string(),
            value: message.encode_to_vec(),
        },
    );
    Ok(())
}

fn pack_new<M: Message>(
    type_url: &str,
    message: &M,
) -> envoy_types_v076::pb::google::protobuf::Any {
    envoy_types_v076::pb::google::protobuf::Any {
        type_url: type_url.to_string(),
        value: message.encode_to_vec(),
    }
}

fn duration(seconds: i64) -> Duration {
    Duration { seconds, nanos: 0 }
}

fn upstream_cluster_name(upstream: &Upstream) -> String {
    let mut hash = Sha256::new();
    hash.update(upstream.scheme.as_bytes());
    hash.update([0]);
    hash.update(upstream.host.as_bytes());
    hash.update([0]);
    hash.update(upstream.port.to_string().as_bytes());
    hash.update([0]);
    hash.update(upstream.protocol.as_bytes());
    format!("joysafeter_up_{}", hex::encode(&hash.finalize()[..10]))
}

fn synthetic_route_base(sandbox_id: &str, route_id: &str) -> String {
    let route_segment = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(route_id);
    format!("/v1/sandbox/{sandbox_id}/route/{route_segment}")
}

fn join_route_path(base: &str, suffix: &str) -> String {
    if suffix == "/" {
        format!("{base}/")
    } else {
        format!(
            "{}/{}",
            base.trim_end_matches('/'),
            suffix.trim_start_matches('/')
        )
    }
}

fn route_path_len(route: &Route) -> usize {
    route
        .r#match
        .as_ref()
        .and_then(|route_match| route_match.path_specifier.as_ref())
        .map(|path| match path {
            route_match::PathSpecifier::Prefix(value) | route_match::PathSpecifier::Path(value) => {
                value.len()
            }
            _ => 0,
        })
        .unwrap_or_default()
}

fn sensitive_headers_except(configured: &[String], keep: &str) -> Vec<String> {
    let mut headers = BTreeSet::from([
        "authorization".to_string(),
        "x-api-key".to_string(),
        "api-key".to_string(),
        "x-goog-api-key".to_string(),
        "proxy-authorization".to_string(),
        "x-joysafeter-sandbox-id".to_string(),
        "x-joysafeter-route-id".to_string(),
    ]);
    headers.extend(configured.iter().cloned());
    headers.remove(&keep.trim().to_ascii_lowercase());
    headers.into_iter().collect()
}

fn timeout_for(profile: &str) -> Duration {
    match profile {
        "streaming" => duration(0),
        "long_running" => duration(300),
        _ => duration(30),
    }
}

fn ext_authz_context(
    context_extensions: BTreeMap<String, String>,
) -> HashMap<String, envoy_types_v076::pb::google::protobuf::Any> {
    HashMap::from([(
        EXT_AUTHZ_FILTER.to_string(),
        pack_new(
            "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute",
            &ModernExtAuthzPerRoute {
                disabled: None,
                check_settings: Some(ModernCheckSettings { context_extensions }),
            },
        ),
    )])
}

fn ext_authz_disabled() -> HashMap<String, envoy_types_v076::pb::google::protobuf::Any> {
    HashMap::from([(
        EXT_AUTHZ_FILTER.to_string(),
        pack_new(
            "type.googleapis.com/envoy.extensions.filters.http.ext_authz.v3.ExtAuthzPerRoute",
            &ModernExtAuthzPerRoute {
                disabled: Some(true),
                check_settings: None,
            },
        ),
    )])
}

fn regex_escape(value: &str) -> String {
    let mut escaped = String::with_capacity(value.len());
    for character in value.chars() {
        if matches!(
            character,
            '\\' | '.' | '^' | '$' | '|' | '?' | '*' | '+' | '(' | ')' | '[' | ']' | '{' | '}'
        ) {
            escaped.push('\\');
        }
        escaped.push(character);
    }
    escaped
}

fn safe_name(value: &str) -> String {
    let value = value
        .chars()
        .map(|character| {
            let character = character.to_ascii_lowercase();
            if character.is_ascii_lowercase()
                || character.is_ascii_digit()
                || matches!(character, '_' | '-')
            {
                character
            } else {
                '_'
            }
        })
        .take(128)
        .collect::<String>();
    if value.is_empty() {
        "resource".to_string()
    } else {
        value
    }
}

#[derive(Clone, PartialEq, Message)]
#[prost(prost_path = "prost14")]
struct ModernCidrRange {
    #[prost(string, tag = "1")]
    address_prefix: String,
    #[prost(message, optional, tag = "2")]
    prefix_len: Option<UInt32Value>,
}

#[derive(Clone, PartialEq, Message)]
#[prost(prost_path = "prost14")]
struct ModernAddressMatcher {
    #[prost(message, repeated, tag = "1")]
    ranges: Vec<ModernCidrRange>,
    #[prost(bool, tag = "2")]
    invert_match: bool,
}

#[derive(Clone, PartialEq, Message)]
#[prost(prost_path = "prost14")]
struct ModernDnsCacheConfig {
    #[prost(string, tag = "1")]
    name: String,
    #[prost(enumeration = "cluster::DnsLookupFamily", tag = "2")]
    dns_lookup_family: i32,
    #[prost(message, optional, tag = "3")]
    dns_refresh_rate: Option<Duration>,
    #[prost(message, optional, tag = "4")]
    host_ttl: Option<Duration>,
    #[prost(message, optional, tag = "5")]
    max_hosts: Option<UInt32Value>,
    #[prost(message, optional, tag = "16")]
    resolved_address_filter: Option<ModernAddressMatcher>,
}

#[derive(Clone, PartialEq, Message)]
#[prost(prost_path = "prost14")]
struct ModernDynamicForwardProxyClusterConfig {
    #[prost(message, optional, tag = "1")]
    dns_cache_config: Option<ModernDnsCacheConfig>,
    #[prost(bool, tag = "2")]
    allow_insecure_cluster_options: bool,
    #[prost(bool, tag = "3")]
    allow_coalesced_connections: bool,
}

#[derive(Clone, PartialEq, Message)]
#[prost(prost_path = "prost14")]
struct ModernDynamicForwardProxyFilterConfig {
    #[prost(message, optional, tag = "1")]
    dns_cache_config: Option<ModernDnsCacheConfig>,
    #[prost(bool, tag = "2")]
    save_upstream_address: bool,
}

#[derive(Clone, PartialEq, Message)]
#[prost(prost_path = "prost14")]
struct ModernExtAuthzPerRoute {
    #[prost(bool, optional, tag = "1")]
    disabled: Option<bool>,
    #[prost(message, optional, tag = "2")]
    check_settings: Option<ModernCheckSettings>,
}

#[derive(Clone, PartialEq, Message)]
#[prost(prost_path = "prost14")]
struct ModernCheckSettings {
    #[prost(btree_map = "string, string", tag = "1")]
    context_extensions: BTreeMap<String, String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    const DIGEST: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    fn policy_json() -> Vec<u8> {
        serde_json::to_vec(&serde_json::json!([{
            "sandbox_id": "018ff000-0000-7000-8000-000000000001",
            "project_id": null,
            "mode": "limited",
            "credential_routes": [{
                "route_id": "llm",
                "consumer_route_id": "llm",
                "kind": "llm",
                "match_authority": "llm.joysafeter.internal",
                "match_path": {"kind": "prefix", "value": "/"},
                "methods": ["POST"],
                "upstream": {"scheme": "https", "host": "api.example.com", "port": 443, "base_path": "/v1", "protocol": "auto"},
                "credential_ref": {"kind": "llm", "secret_name": "provider", "secret_key": "token"},
                "inject_header": "authorization",
                "inject_scheme": {"kind": "bearer"},
                "remove_headers": ["authorization", "x-api-key"],
                "timeout_profile": "streaming",
                "websocket": false
            }],
            "allowed_public_hosts": ["downloads.example.com"],
            "denied_cidrs": ["10.0.0.0/8"]
        }]))
        .unwrap()
    }

    #[test]
    fn compiles_deterministic_lds_rds_cds_without_secret_values() {
        let policies = policy_json();
        let first = compile_kubernetes(
            &CompilerConfig::default(),
            CompileInput {
                snapshot_group_key: "v2:node-a",
                source_group_key: "v2:node-a",
                generation: 42,
                content_sha256: DIGEST,
                policy_schema_version: policy::POLICY_SCHEMA_VERSION,
                desired_policies: &policies,
            },
        )
        .unwrap();
        let second = compile_kubernetes(
            &CompilerConfig::default(),
            CompileInput {
                snapshot_group_key: "v2:node-a",
                source_group_key: "v2:node-a",
                generation: 42,
                content_sha256: DIGEST,
                policy_schema_version: policy::POLICY_SCHEMA_VERSION,
                desired_policies: &policies,
            },
        )
        .unwrap();

        assert_eq!(first, second);
        assert_eq!(first.resources[CLUSTER_TYPE_URL].len(), 3);
        assert_eq!(first.resources[ROUTE_TYPE_URL].len(), 2);
        assert_eq!(first.resources[LISTENER_TYPE_URL].len(), 2);
        let encoded = first
            .resources
            .values()
            .flat_map(|typed| typed.values())
            .flat_map(|resource| resource.value.iter().copied())
            .collect::<Vec<_>>();
        let encoded = String::from_utf8_lossy(&encoded);
        assert!(!encoded.contains("provider"));
        assert!(!encoded.contains("token"));
    }

    #[test]
    fn compiles_docker_pipe_listeners_and_control_route() {
        let policies = policy_json();
        let snapshot = compile_for_provider(
            &CompilerConfig::default(),
            "docker",
            CompileInput {
                snapshot_group_key: "v2:docker-node",
                source_group_key: "v1:canonical-source",
                generation: 42,
                content_sha256: DIGEST,
                policy_schema_version: policy::POLICY_SCHEMA_VERSION,
                desired_policies: &policies,
            },
        )
        .unwrap();

        assert_eq!(snapshot.group_key, "v2:docker-node");
        let encoded_routes = snapshot.resources[ROUTE_TYPE_URL]
            .values()
            .flat_map(|resource| resource.value.iter().copied())
            .collect::<Vec<_>>();
        assert!(String::from_utf8_lossy(&encoded_routes).contains("v1:canonical-source"));
        assert_eq!(snapshot.resources[CLUSTER_TYPE_URL].len(), 3);
        assert_eq!(snapshot.resources[ROUTE_TYPE_URL].len(), 2);
        assert_eq!(snapshot.resources[LISTENER_TYPE_URL].len(), 2);

        let resource_id = "018ff000_0000_7000_8000_000000000001";
        let http = Listener::decode(
            snapshot.resources[LISTENER_TYPE_URL][&format!("joysafeter_{resource_id}_http")]
                .value
                .as_slice(),
        )
        .unwrap();
        let grpc = Listener::decode(
            snapshot.resources[LISTENER_TYPE_URL][&format!("joysafeter_{resource_id}_grpc")]
                .value
                .as_slice(),
        )
        .unwrap();
        assert!(matches!(
            http.address.and_then(|address| address.address),
            Some(address::Address::Pipe(Pipe { path, .. }))
                if path == "/sockets/018ff000-0000-7000-8000-000000000001/http.sock"
        ));
        assert!(matches!(
            grpc.address.and_then(|address| address.address),
            Some(address::Address::Pipe(Pipe { path, .. }))
                if path == "/sockets/018ff000-0000-7000-8000-000000000001/grpc.sock"
        ));
        let encoded_grpc = snapshot.resources[LISTENER_TYPE_URL]
            [&format!("joysafeter_{resource_id}_grpc")]
            .value
            .as_slice();
        assert!(!String::from_utf8_lossy(encoded_grpc).contains("ext_authz"));
    }

    #[test]
    fn modern_dns_cache_encodes_resolved_address_filter_field_16() {
        let cache = dynamic_dns_cache(&[ModernCidrRange {
            address_prefix: "10.0.0.0".to_string(),
            prefix_len: Some(UInt32Value { value: 8 }),
        }]);
        let bytes = cache.encode_to_vec();
        assert!(bytes.windows(2).any(|window| window == [0x82, 0x01]));
    }

    #[test]
    fn rust_compiler_matches_canonical_parity_fixtures() {
        for (provider, fixture) in [
            (
                "k8s",
                serde_json::from_slice::<serde_json::Value>(include_bytes!(
                    "../../testdata/compiler/parity-kubernetes-v1.json"
                ))
                .unwrap(),
            ),
            (
                "docker",
                serde_json::from_slice::<serde_json::Value>(include_bytes!(
                    "../../testdata/compiler/parity-docker-v1.json"
                ))
                .unwrap(),
            ),
        ] {
            let policies = serde_json::to_vec(&fixture["policies"]).unwrap();
            let snapshot = compile_for_provider(
                &CompilerConfig::default(),
                provider,
                CompileInput {
                    snapshot_group_key: fixture["group_key"].as_str().unwrap(),
                    source_group_key: fixture["group_key"].as_str().unwrap(),
                    generation: fixture["generation"].as_i64().unwrap(),
                    content_sha256: fixture["content_sha256"].as_str().unwrap(),
                    policy_schema_version: fixture["policy_schema_version"].as_i64().unwrap()
                        as i32,
                    desired_policies: &policies,
                },
            )
            .unwrap();

            for (type_url, fixture_key) in [
                (CLUSTER_TYPE_URL, "clusters"),
                (ROUTE_TYPE_URL, "routes"),
                (LISTENER_TYPE_URL, "listeners"),
            ] {
                let actual = snapshot.resources[type_url]
                    .keys()
                    .cloned()
                    .collect::<Vec<_>>();
                let expected = fixture["expected_resources"][fixture_key]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|value| value.as_str().unwrap().to_string())
                    .collect::<Vec<_>>();
                assert_eq!(actual, expected, "provider {provider} {fixture_key}");
            }
        }
    }
}
