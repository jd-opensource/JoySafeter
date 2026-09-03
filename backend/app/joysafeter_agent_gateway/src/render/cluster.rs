use envoy_types::pb::google::protobuf::Any;
use prost::Message;

use crate::domain::egress_policy::ClusterSpec;

use super::{pack_any, CLUSTER_TYPE_URL};

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
