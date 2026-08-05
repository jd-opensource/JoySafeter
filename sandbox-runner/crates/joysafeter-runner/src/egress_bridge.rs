//! In-process HTTP egress bridge.
//!
//! The sandbox runs with `network=none`; its only path to the outside world is a
//! per-sandbox Unix socket (`/sockets/<id>/http.sock`) bound on the host by the
//! shared Envoy proxy. Agent CLIs speak HTTP proxy over TCP, so we bridge
//! `127.0.0.1:<port>` (TCP) to that Unix socket.
//!
//! This replaces the previous `socat TCP-LISTEN,fork ... UNIX-CONNECT:...`
//! sidecar. Doing it in-process removes an external binary dependency and — more
//! importantly — removes the startup race: the TCP listener binds *immediately*,
//! and each accepted connection connects to the Envoy socket lazily with a short
//! retry. Requests that arrive before Envoy has bound the socket therefore wait
//! briefly and then succeed, instead of failing with "connection refused" /
//! "socket not ready".

use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

use tokio::net::{TcpListener, TcpStream, UnixStream};
use tracing::{debug, info, warn};

/// TCP port the in-process HTTP proxy bridge listens on. Agent CLIs are pointed
/// here via `HTTP_PROXY`/`HTTPS_PROXY`.
pub const BRIDGE_PORT: u16 = 3128;

/// How long a single upstream (Unix socket) connect attempt may take.
const UDS_CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
/// Per-connection budget for the Envoy socket to appear before the client
/// connection is dropped. Generous enough to cover Envoy's LDS reload window,
/// short enough that a genuinely-broken egress path fails a request instead of
/// hanging it forever.
const UDS_READY_BUDGET: Duration = Duration::from_secs(30);
/// Backoff between lazy connect retries while the socket is not yet present.
const UDS_RETRY_INTERVAL: Duration = Duration::from_millis(100);

/// Bind the bridge listener on loopback. Returns immediately once bound, so the
/// proxy endpoint is reachable before Envoy has necessarily created the upstream
/// socket. The caller spawns [`serve`] to handle connections.
pub async fn bind() -> io::Result<TcpListener> {
    TcpListener::bind(("127.0.0.1", BRIDGE_PORT)).await
}

/// Accept loop: forward every TCP connection to the Envoy Unix socket. Runs
/// until the listener errors unrecoverably. Each connection is handled in its
/// own task so a slow upstream connect never blocks new accepts.
pub async fn serve(listener: TcpListener, http_sock: PathBuf) {
    info!(
        port = BRIDGE_PORT,
        upstream = %http_sock.display(),
        "In-process HTTP proxy bridge listening"
    );
    loop {
        match listener.accept().await {
            Ok((client, _peer)) => {
                let http_sock = http_sock.clone();
                tokio::spawn(async move {
                    if let Err(e) = proxy_connection(client, &http_sock).await {
                        debug!(error = %e, "egress bridge connection closed with error");
                    }
                });
            }
            Err(e) => {
                // A transient accept error (e.g. EMFILE) shouldn't kill the
                // bridge; back off briefly and keep serving.
                warn!(error = %e, "egress bridge accept error; retrying");
                tokio::time::sleep(UDS_RETRY_INTERVAL).await;
            }
        }
    }
}

/// Connect to the Envoy Unix socket, retrying with backoff until it appears or
/// the ready budget elapses, then splice the TCP client and the Unix socket
/// bidirectionally.
async fn proxy_connection(mut client: TcpStream, http_sock: &Path) -> io::Result<()> {
    let mut upstream = connect_upstream(http_sock).await?;
    // Bidirectional copy; returns when either side closes.
    tokio::io::copy_bidirectional(&mut client, &mut upstream)
        .await
        .map(|_| ())
}

/// Lazily connect to the Envoy socket, tolerating the socket not existing yet.
/// This is what removes the cold-start race: the first requests after sandbox
/// start retry quietly until Envoy binds the listener pipe.
async fn connect_upstream(http_sock: &Path) -> io::Result<UnixStream> {
    let deadline = tokio::time::Instant::now() + UDS_READY_BUDGET;
    let mut logged_wait = false;
    loop {
        match tokio::time::timeout(UDS_CONNECT_TIMEOUT, UnixStream::connect(http_sock)).await {
            Ok(Ok(stream)) => return Ok(stream),
            Ok(Err(e)) => {
                if tokio::time::Instant::now() >= deadline {
                    warn!(
                        path = %http_sock.display(),
                        error = %e,
                        "egress upstream socket not ready within budget; dropping request"
                    );
                    return Err(e);
                }
                if !logged_wait {
                    debug!(path = %http_sock.display(), "egress upstream socket not ready yet; retrying");
                    logged_wait = true;
                }
                tokio::time::sleep(UDS_RETRY_INTERVAL).await;
            }
            Err(_) => {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "timed out connecting to egress upstream socket",
                ));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::UnixListener;

    /// The bridge forwards bytes both directions once the upstream socket exists.
    #[tokio::test]
    async fn bridge_forwards_bidirectionally() {
        let dir = tempfile::tempdir().unwrap();
        let sock = dir.path().join("http.sock");

        // Fake "Envoy": echo-with-prefix Unix server.
        let server_sock = sock.clone();
        let uds = UnixListener::bind(&server_sock).unwrap();
        tokio::spawn(async move {
            let (mut conn, _) = uds.accept().await.unwrap();
            let mut buf = [0u8; 64];
            let n = conn.read(&mut buf).await.unwrap();
            conn.write_all(b"pong:").await.unwrap();
            conn.write_all(&buf[..n]).await.unwrap();
            conn.flush().await.unwrap();
        });

        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let addr = listener.local_addr().unwrap();
        let up = sock.clone();
        tokio::spawn(async move {
            let (client, _) = listener.accept().await.unwrap();
            proxy_connection(client, &up).await.unwrap();
        });

        let mut client = TcpStream::connect(addr).await.unwrap();
        client.write_all(b"ping").await.unwrap();
        client.flush().await.unwrap();
        let mut out = Vec::new();
        client.read_to_end(&mut out).await.unwrap();
        assert_eq!(out, b"pong:ping");
    }

    /// A connection that arrives before the upstream socket exists retries and
    /// succeeds once the socket appears — the cold-start race fix.
    #[tokio::test]
    async fn bridge_waits_for_late_upstream_socket() {
        let dir = tempfile::tempdir().unwrap();
        let sock = dir.path().join("http.sock");

        // Start connecting before any Unix listener exists.
        let up = sock.clone();
        let connect = tokio::spawn(async move { connect_upstream(&up).await.is_ok() });

        // Bring the socket up shortly after.
        tokio::time::sleep(Duration::from_millis(300)).await;
        let uds = UnixListener::bind(&sock).unwrap();
        tokio::spawn(async move {
            let _ = uds.accept().await;
        });

        assert!(connect.await.unwrap(), "should connect once socket appears");
    }
}
