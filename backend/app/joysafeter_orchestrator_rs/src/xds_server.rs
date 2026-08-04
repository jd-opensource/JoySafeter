use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use envoy_types::pb::envoy::service::discovery::v3::aggregated_discovery_service_server::AggregatedDiscoveryServiceServer;
use tokio::task::JoinHandle;
use tonic::service::interceptor::InterceptedService;
use tonic::transport::{Certificate, Identity, Server, ServerTlsConfig};
use tonic::{Request, Status};
use tracing::{error, info};
use x509_parser::extensions::GeneralName;
use x509_parser::parse_x509_certificate;

use crate::sandbox::lds_backend::DeltaXdsServer;

const MAX_XDS_MESSAGE_BYTES: usize = 16 * 1024 * 1024;
const MAX_CONCURRENT_XDS_STREAMS: u32 = 10_000;

#[derive(Debug, Clone)]
pub struct XdsTlsConfig {
    pub enabled: bool,
    pub cert_file: String,
    pub key_file: String,
    pub client_ca_file: String,
    pub client_dns_san: String,
}

#[allow(clippy::result_large_err)]
pub async fn start_xds_server(
    addr: SocketAddr,
    xds: Arc<DeltaXdsServer>,
    tls: XdsTlsConfig,
) -> anyhow::Result<JoinHandle<()>> {
    let expected_client_dns_san = if tls.enabled {
        anyhow::ensure!(
            !tls.client_dns_san.trim().is_empty(),
            "Envoy xDS mTLS requires an expected client DNS SAN"
        );
        Some(tls.client_dns_san.clone())
    } else {
        None
    };

    let ads = AggregatedDiscoveryServiceServer::from_arc(xds)
        .max_decoding_message_size(MAX_XDS_MESSAGE_BYTES)
        .max_encoding_message_size(MAX_XDS_MESSAGE_BYTES);
    let ads = InterceptedService::new(ads, move |request: Request<()>| {
        if let Some(expected) = expected_client_dns_san.as_deref() {
            verify_peer_dns_san(&request, expected)?;
        }
        Ok(request)
    });

    let mut builder = Server::builder()
        .tcp_keepalive(Some(Duration::from_secs(30)))
        .http2_keepalive_interval(Some(Duration::from_secs(30)))
        .http2_keepalive_timeout(Some(Duration::from_secs(5)))
        .max_concurrent_streams(Some(MAX_CONCURRENT_XDS_STREAMS));
    if tls.enabled {
        let certificate = tokio::fs::read(&tls.cert_file).await?;
        let private_key = tokio::fs::read(&tls.key_file).await?;
        let client_ca = tokio::fs::read(&tls.client_ca_file).await?;
        builder = builder.tls_config(
            ServerTlsConfig::new()
                .identity(Identity::from_pem(certificate, private_key))
                .client_ca_root(Certificate::from_pem(client_ca)),
        )?;
    }

    let mtls = tls.enabled;
    Ok(tokio::spawn(async move {
        info!(%addr, mtls, "dedicated Rust Envoy ADS server listening");
        if let Err(server_error) = builder.add_service(ads).serve(addr).await {
            error!(error = %server_error, "dedicated Rust Envoy ADS server failed");
        }
    }))
}

#[allow(clippy::result_large_err)]
fn verify_peer_dns_san(request: &Request<()>, expected_dns_san: &str) -> Result<(), Status> {
    let certificates = request
        .peer_certs()
        .ok_or_else(|| Status::unauthenticated("Envoy xDS client certificate is required"))?;
    let certificate = certificates
        .first()
        .ok_or_else(|| Status::unauthenticated("Envoy xDS client certificate is required"))?;
    let (_, certificate) = parse_x509_certificate(certificate.as_ref())
        .map_err(|_| Status::unauthenticated("Envoy xDS client certificate is invalid"))?;
    let subject_alt_name = certificate
        .subject_alternative_name()
        .map_err(|_| Status::unauthenticated("Envoy xDS client certificate SAN is invalid"))?
        .ok_or_else(|| Status::permission_denied("Envoy xDS client certificate has no DNS SAN"))?;
    if has_exact_dns_san(&subject_alt_name.value.general_names, expected_dns_san) {
        Ok(())
    } else {
        Err(Status::permission_denied(
            "Envoy xDS client certificate identity is not allowed",
        ))
    }
}

fn has_exact_dns_san(names: &[GeneralName<'_>], expected_dns_san: &str) -> bool {
    names
        .iter()
        .any(|name| matches!(name, GeneralName::DNSName(value) if *value == expected_dns_san))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn client_identity_requires_exact_dns_san() {
        let expected = "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local";
        assert!(has_exact_dns_san(
            &[GeneralName::DNSName(expected)],
            expected
        ));
        assert!(!has_exact_dns_san(
            &[GeneralName::DNSName(
                "*.joysafeter-egress.svc.cluster.local"
            )],
            expected
        ));
        assert!(!has_exact_dns_san(
            &[GeneralName::DNSName(
                "other-client.joysafeter-egress.svc.cluster.local"
            )],
            expected
        ));
    }

    #[test]
    fn mtls_interceptor_rejects_missing_peer_certificate() {
        let error = verify_peer_dns_san(
            &Request::new(()),
            "joysafeter-egress-envoy.joysafeter-egress.svc.cluster.local",
        )
        .expect_err("missing certificate must fail closed");
        assert_eq!(error.code(), tonic::Code::Unauthenticated);
    }
}
