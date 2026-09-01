use std::future::Future;
use std::io;
use std::net::SocketAddr;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use envoy_types::pb::envoy::service::discovery::v3::aggregated_discovery_service_server::AggregatedDiscoveryServiceServer;
use futures::StreamExt;
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
use tokio::net::TcpListener;
use tokio::sync::watch;
use tokio::task::JoinHandle;
use tokio_stream::wrappers::TcpListenerStream;
use tonic::service::interceptor::InterceptedService;
use tonic::transport::server::Connected;
use tonic::Request;
use tracing::{debug, error, info, warn};

use super::auth::XdsClientAuthenticator;
use super::authority::AuthorityPhase;
use super::control_plane::XdsControlPlane;
use super::metrics::XdsStreamRejection;

type PhaseChange =
    Pin<Box<dyn Future<Output = Option<watch::Receiver<AuthorityPhase>>> + Send + 'static>>;

struct AuthorityBoundIo {
    inner: tokio::net::TcpStream,
    epoch: u64,
    phase_change: PhaseChange,
    revoked: bool,
}

impl AuthorityBoundIo {
    fn new(
        inner: tokio::net::TcpStream,
        epoch: u64,
        receiver: watch::Receiver<AuthorityPhase>,
    ) -> Self {
        Self {
            inner,
            epoch,
            phase_change: wait_for_phase_change(receiver),
            revoked: false,
        }
    }

    fn poll_authority(&mut self, cx: &mut Context<'_>) -> io::Result<()> {
        if self.revoked {
            return Err(authority_revoked_error(self.epoch));
        }
        loop {
            match self.phase_change.as_mut().poll(cx) {
                Poll::Pending => return Ok(()),
                Poll::Ready(None) => {
                    self.revoked = true;
                    return Err(authority_revoked_error(self.epoch));
                }
                Poll::Ready(Some(receiver)) => {
                    let phase = *receiver.borrow();
                    if serving_epoch(phase) != Some(self.epoch) {
                        self.revoked = true;
                        debug!(epoch = self.epoch, ?phase, "closing stale xDS transport");
                        return Err(authority_revoked_error(self.epoch));
                    }
                    self.phase_change = wait_for_phase_change(receiver);
                }
            }
        }
    }
}

impl AsyncRead for AuthorityBoundIo {
    fn poll_read(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &mut ReadBuf<'_>,
    ) -> Poll<io::Result<()>> {
        self.poll_authority(cx)?;
        Pin::new(&mut self.inner).poll_read(cx, buffer)
    }
}

impl AsyncWrite for AuthorityBoundIo {
    fn poll_write(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buffer: &[u8],
    ) -> Poll<Result<usize, io::Error>> {
        self.poll_authority(cx)?;
        Pin::new(&mut self.inner).poll_write(cx, buffer)
    }

    fn poll_flush(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<Result<(), io::Error>> {
        self.poll_authority(cx)?;
        Pin::new(&mut self.inner).poll_flush(cx)
    }

    fn poll_shutdown(
        mut self: Pin<&mut Self>,
        cx: &mut Context<'_>,
    ) -> Poll<Result<(), io::Error>> {
        Pin::new(&mut self.inner).poll_shutdown(cx)
    }
}

impl Connected for AuthorityBoundIo {
    type ConnectInfo = ();

    fn connect_info(&self) -> Self::ConnectInfo {}
}

fn wait_for_phase_change(mut receiver: watch::Receiver<AuthorityPhase>) -> PhaseChange {
    Box::pin(async move {
        receiver.changed().await.ok()?;
        Some(receiver)
    })
}

fn serving_epoch(phase: AuthorityPhase) -> Option<u64> {
    match phase {
        AuthorityPhase::RecoveryServing { epoch } | AuthorityPhase::Ready { epoch } => Some(epoch),
        AuthorityPhase::Standby
        | AuthorityPhase::Staging { .. }
        | AuthorityPhase::Revoked { .. } => None,
    }
}

fn authority_revoked_error(epoch: u64) -> io::Error {
    io::Error::new(
        io::ErrorKind::ConnectionReset,
        format!("xDS authority epoch {epoch} was revoked"),
    )
}

pub async fn start_xds_server(
    addr: SocketAddr,
    service: XdsControlPlane,
    authenticator: Arc<dyn XdsClientAuthenticator>,
) -> anyhow::Result<JoinHandle<()>> {
    let listener = TcpListener::bind(addr).await?;
    let authority = service.authority();
    let metrics = service.metrics();
    let ads = AggregatedDiscoveryServiceServer::from_arc(service.ads_service());
    let authenticated_ads = InterceptedService::new(ads, move |mut request: Request<()>| {
        match authenticator.authenticate(&request) {
            Ok(principal) => {
                metrics.record_authenticated_stream();
                request.extensions_mut().insert(principal);
                Ok(request)
            }
            Err(error) => {
                metrics.record_rejected_stream(XdsStreamRejection::Unauthenticated);
                Err(error)
            }
        }
    });

    let incoming = TcpListenerStream::new(listener).filter_map(move |accepted| {
        let authority = authority.clone();
        async move {
            match accepted {
                Ok(socket) => {
                    let phase = authority.phase();
                    let Some(epoch) = serving_epoch(phase) else {
                        debug!(?phase, "rejecting xDS connection without serving authority");
                        return None;
                    };
                    let receiver = authority.subscribe();
                    if serving_epoch(*receiver.borrow()) != Some(epoch) {
                        debug!(
                            epoch,
                            "rejecting xDS connection across authority transition"
                        );
                        return None;
                    }
                    Some(Ok(AuthorityBoundIo::new(socket, epoch, receiver)))
                }
                Err(error) => {
                    warn!(%error, "xDS listener accept failed");
                    Some(Err(error))
                }
            }
        }
    });

    let handle = tokio::spawn(async move {
        info!(addr = %addr, "authenticated xDS server listening");
        if let Err(error) = tonic::transport::Server::builder()
            .add_service(authenticated_ads)
            .serve_with_incoming(incoming)
            .await
        {
            error!(addr = %addr, %error, "xDS server failed");
        }
    });
    Ok(handle)
}
