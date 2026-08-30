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
use std::sync::Arc;
use std::time::Duration;

use tokio::io::{AsyncReadExt, AsyncWriteExt};
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
pub async fn serve(listener: TcpListener, http_sock: PathBuf, proxy_authorization: Arc<str>) {
    info!(
        port = BRIDGE_PORT,
        upstream = %http_sock.display(),
        "In-process HTTP proxy bridge listening"
    );
    loop {
        match listener.accept().await {
            Ok((client, _peer)) => {
                let http_sock = http_sock.clone();
                let proxy_authorization = Arc::clone(&proxy_authorization);
                tokio::spawn(async move {
                    if let Err(e) = proxy_connection(client, &http_sock, &proxy_authorization).await
                    {
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
///
/// If the client opens with an HTTP `CONNECT` tunnel (as pi's Node/undici client
/// does under `NODE_USE_ENV_PROXY=1`), the CONNECT is terminated here first, and
/// the tunnelled request-line is rewritten from origin-form (`POST /path`) to
/// absolute-form (`POST http://host/path`) before it reaches Envoy. Envoy's
/// egress listener is a forward proxy whose route table matches only absolute-
/// form requests; origin-form (and CONNECT) yield 404 route_not_found and an
/// empty turn. For both CONNECT and absolute-form clients, the bridge owns proxy
/// authentication and injects the credential before forwarding to Envoy.
async fn proxy_connection(
    mut client: TcpStream,
    http_sock: &Path,
    proxy_authorization: &str,
) -> io::Result<()> {
    let tunnel = terminate_connect(&mut client).await?;
    let mut upstream = connect_upstream(http_sock).await?;
    forward_authenticated_request(
        &mut client,
        &mut upstream,
        tunnel.as_ref(),
        proxy_authorization,
    )
    .await?;
    // Bidirectional copy; returns when either side closes.
    tokio::io::copy_bidirectional(&mut client, &mut upstream)
        .await
        .map(|_| ())
}

/// If `client` opens with an HTTP `CONNECT` request, consume that preamble, ack
/// it with `200 Connection Established`, and return the tunnel authority
/// (`host[:port]`). Otherwise consume nothing and return `None`.
struct ConnectTunnel {
    authority: String,
}

async fn terminate_connect(client: &mut TcpStream) -> io::Result<Option<ConnectTunnel>> {
    let Some(preamble_len) = detect_connect_preamble(client).await? else {
        return Ok(None);
    };
    let mut preamble = vec![0u8; preamble_len];
    client.read_exact(&mut preamble).await?;
    let tunnel = parse_connect_tunnel(&preamble);
    client
        .write_all(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        .await?;
    client.flush().await?;
    Ok(Some(tunnel))
}

fn parse_connect_tunnel(preamble: &[u8]) -> ConnectTunnel {
    let text = String::from_utf8_lossy(preamble);
    let mut lines = text.split("\r\n");
    let authority = lines
        .next()
        .and_then(|line| line.split(' ').nth(1))
        .unwrap_or("")
        .to_string();
    ConnectTunnel { authority }
}

/// Read the first tunnelled HTTP request's header block, rewrite the request-line
/// to absolute-form using `authority`, force `Connection: close` (so each tunnel
/// carries exactly one request — no body framing needed), and forward it plus any
/// already-received body bytes to Envoy. The remainder of the request body and
/// the response are then handled by the caller's bidirectional splice.
async fn forward_authenticated_request(
    client: &mut TcpStream,
    upstream: &mut UnixStream,
    tunnel: Option<&ConnectTunnel>,
    proxy_authorization: &str,
) -> io::Result<()> {
    const MAX_HEAD: usize = 64 * 1024;
    let mut buf: Vec<u8> = Vec::with_capacity(8192);
    let mut tmp = [0u8; 4096];
    loop {
        if let Some(pos) = find_subslice(&buf, b"\r\n\r\n") {
            let head = &buf[..pos];
            let body_start = pos + 4;
            upstream
                .write_all(&rewrite_request_head(head, tunnel, proxy_authorization))
                .await?;
            if body_start < buf.len() {
                upstream.write_all(&buf[body_start..]).await?;
            }
            upstream.flush().await?;
            return Ok(());
        }
        if buf.len() > MAX_HEAD {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "egress request header exceeds bridge limit",
            ));
        }
        let n = client.read(&mut tmp).await?;
        if n == 0 {
            return Err(io::Error::new(
                io::ErrorKind::UnexpectedEof,
                "egress client closed before completing request headers",
            ));
        }
        buf.extend_from_slice(&tmp[..n]);
    }
}

/// Rewrite an HTTP request header block (request-line + headers, without the
/// trailing blank line) so Envoy's forward proxy will route it: origin-form
/// request-target becomes absolute-form using `authority`, and any keep-alive is
/// downgraded to `Connection: close`. Returns the new block including the
/// terminating `\r\n\r\n`.
fn rewrite_request_head(
    head: &[u8],
    tunnel: Option<&ConnectTunnel>,
    proxy_authorization: &str,
) -> Vec<u8> {
    let text = String::from_utf8_lossy(head);
    let mut lines = text.split("\r\n");
    let request_line = lines.next().unwrap_or("");

    let mut parts = request_line.splitn(3, ' ');
    let method = parts.next().unwrap_or("");
    let target = parts.next().unwrap_or("");
    let version = parts.next().unwrap_or("HTTP/1.1");
    let new_request_line = if target.starts_with('/') && tunnel.is_some() {
        // Drop the default :80 so the authority matches the proven-working form.
        let authority = &tunnel.expect("tunnel checked above").authority;
        let host = authority.strip_suffix(":80").unwrap_or(authority);
        format!("{method} http://{host}{target} {version}")
    } else {
        request_line.to_string()
    };

    let mut out = vec![new_request_line];
    for line in lines {
        let lower = line.to_ascii_lowercase();
        if lower.starts_with("connection:")
            || lower.starts_with("proxy-connection:")
            || lower.starts_with("proxy-authorization:")
        {
            continue;
        }
        out.push(line.to_string());
    }
    out.push(format!("Proxy-Authorization: {proxy_authorization}"));
    out.push("Connection: close".to_string());

    let mut bytes = out.join("\r\n").into_bytes();
    bytes.extend_from_slice(b"\r\n\r\n");
    bytes
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

/// Peek (without consuming) at the start of `client` to detect an HTTP `CONNECT`
/// tunnel request. Returns `Some(preamble_len)` — the byte length of the request
/// line plus headers up to and including the terminating blank line — when the
/// stream opens with `CONNECT `, else `None`. Any bytes the client pipelines
/// after the preamble stay in the socket buffer for the subsequent splice.
async fn detect_connect_preamble(client: &TcpStream) -> io::Result<Option<usize>> {
    const CONNECT: &[u8] = b"CONNECT ";
    let mut buf = vec![0u8; 8192];
    // Bounded so a client that opens the connection but never completes the
    // header block can't spin here forever; it just falls through to a splice.
    for _ in 0..UDS_READY_BUDGET.as_millis() as u64 / UDS_RETRY_INTERVAL.as_millis() as u64 {
        let n = client.peek(&mut buf).await?;
        if n == 0 {
            return Ok(None); // client closed before sending anything
        }
        let head = &buf[..n];
        if head.len() < CONNECT.len() {
            // Too few bytes to decide. If what we have is a prefix of "CONNECT ",
            // wait for more; otherwise it can't be a CONNECT.
            if CONNECT.starts_with(head) {
                tokio::time::sleep(UDS_RETRY_INTERVAL).await;
                continue;
            }
            return Ok(None);
        }
        if !head.starts_with(CONNECT) {
            return Ok(None);
        }
        if let Some(pos) = find_subslice(head, b"\r\n\r\n") {
            return Ok(Some(pos + 4));
        }
        if n == buf.len() {
            // Header block larger than the peek buffer: not a well-formed CONNECT
            // we handle; splice through rather than buffer unboundedly.
            return Ok(None);
        }
        tokio::time::sleep(UDS_RETRY_INTERVAL).await;
    }
    Ok(None)
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
            let mut buf = [0u8; 1024];
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
            proxy_connection(client, &up, "Basic bridge-token")
                .await
                .unwrap();
        });

        let mut client = TcpStream::connect(addr).await.unwrap();
        client
            .write_all(b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n")
            .await
            .unwrap();
        client.flush().await.unwrap();
        let mut out = Vec::new();
        client.read_to_end(&mut out).await.unwrap();
        let output = String::from_utf8(out).unwrap();
        assert!(output.starts_with("pong:GET http://example.com/ HTTP/1.1\r\n"));
        assert!(output.contains("Proxy-Authorization: Basic bridge-token\r\n"));
    }

    /// pi's Node/undici client (NODE_USE_ENV_PROXY=1) reaches the LLM endpoint by
    /// opening an HTTP `CONNECT host:port` tunnel to this proxy, then sending the
    /// real request through it in ORIGIN form (`POST /path`). Envoy's egress
    /// listener is a forward proxy whose route table matches only ABSOLUTE-form
    /// requests (`POST http://host/path`) — origin-form yields 404 route_not_found
    /// and an empty pi turn (confirmed live). So the bridge must terminate CONNECT
    /// (ack `200`), then rewrite the tunnelled request-line to absolute-form using
    /// the CONNECT authority before forwarding to Envoy.
    #[tokio::test]
    async fn bridge_terminates_connect_and_rewrites_to_absolute_form() {
        let dir = tempfile::tempdir().unwrap();
        let sock = dir.path().join("http.sock");

        // Fake Envoy mirroring the real forward proxy: 200 for absolute-form,
        // 404 for anything else (origin-form, CONNECT).
        let server_sock = sock.clone();
        let uds = UnixListener::bind(&server_sock).unwrap();
        let seen = std::sync::Arc::new(tokio::sync::Mutex::new(String::new()));
        let seen_w = seen.clone();
        tokio::spawn(async move {
            let (mut conn, _) = uds.accept().await.unwrap();
            let mut buf = [0u8; 512];
            let n = conn.read(&mut buf).await.unwrap();
            let first_line = String::from_utf8_lossy(&buf[..n])
                .lines()
                .next()
                .unwrap_or("")
                .to_string();
            *seen_w.lock().await = first_line.clone();
            let resp = if first_line.starts_with("POST http://") {
                "HTTP/1.1 200 OK\r\ncontent-length:2\r\nconnection:close\r\n\r\nok"
            } else {
                "HTTP/1.1 404 Not Found\r\ncontent-length:0\r\nconnection:close\r\n\r\n"
            };
            conn.write_all(resp.as_bytes()).await.unwrap();
            conn.flush().await.unwrap();
        });

        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let addr = listener.local_addr().unwrap();
        let up = sock.clone();
        tokio::spawn(async move {
            let (client, _) = listener.accept().await.unwrap();
            proxy_connection(client, &up, "Basic bridge-token")
                .await
                .unwrap();
        });

        let mut client = TcpStream::connect(addr).await.unwrap();
        // Phase 1: the CONNECT preamble (what undici sends first).
        client
            .write_all(
                b"CONNECT ai-api.jdcloud.com:80 HTTP/1.1\r\nHost: ai-api.jdcloud.com:80\r\n\r\n",
            )
            .await
            .unwrap();
        client.flush().await.unwrap();
        // Phase 2: the bridge must ack the tunnel before the client sends the body.
        let mut ack = [0u8; 64];
        let n = client.read(&mut ack).await.unwrap();
        assert!(
            String::from_utf8_lossy(&ack[..n]).starts_with("HTTP/1.1 200"),
            "expected a CONNECT 200 ack from the bridge, got: {:?}",
            String::from_utf8_lossy(&ack[..n])
        );
        // Phase 3: the real (inner) request in ORIGIN form, tunnelled.
        client
            .write_all(b"POST /v1/chat/completions HTTP/1.1\r\nHost: ai-api.jdcloud.com\r\ncontent-length:2\r\n\r\n{}")
            .await
            .unwrap();
        client.flush().await.unwrap();

        let mut out = Vec::new();
        client.read_to_end(&mut out).await.unwrap();

        // Envoy must have received the request REWRITTEN to absolute-form.
        assert_eq!(
            *seen.lock().await,
            "POST http://ai-api.jdcloud.com/v1/chat/completions HTTP/1.1",
            "bridge should rewrite the tunnelled origin-form request to absolute-form"
        );
        assert!(
            String::from_utf8_lossy(&out).contains("ok"),
            "client should receive Envoy's 200 response through the tunnel, got: {:?}",
            String::from_utf8_lossy(&out)
        );
    }

    #[tokio::test]
    async fn bridge_injects_proxy_authorization_when_terminating_connect() {
        let dir = tempfile::tempdir().unwrap();
        let sock = dir.path().join("http.sock");

        let server_sock = sock.clone();
        let uds = UnixListener::bind(&server_sock).unwrap();
        let seen = std::sync::Arc::new(tokio::sync::Mutex::new(String::new()));
        let seen_w = seen.clone();
        tokio::spawn(async move {
            let (mut conn, _) = uds.accept().await.unwrap();
            let mut buf = [0u8; 1024];
            let n = conn.read(&mut buf).await.unwrap();
            *seen_w.lock().await = String::from_utf8_lossy(&buf[..n]).to_string();
            conn.write_all(b"HTTP/1.1 200 OK\r\ncontent-length:2\r\nconnection:close\r\n\r\nok")
                .await
                .unwrap();
            conn.flush().await.unwrap();
        });

        let listener = TcpListener::bind(("127.0.0.1", 0)).await.unwrap();
        let addr = listener.local_addr().unwrap();
        let up = sock.clone();
        tokio::spawn(async move {
            let (client, _) = listener.accept().await.unwrap();
            proxy_connection(client, &up, "Basic c2FuZGJveDplZ3Jlc3MtdG9rZW4=")
                .await
                .unwrap();
        });

        let mut client = TcpStream::connect(addr).await.unwrap();
        client
            .write_all(
                b"CONNECT ai-api.jdcloud.com:80 HTTP/1.1\r\nHost: ai-api.jdcloud.com:80\r\n\r\n",
            )
            .await
            .unwrap();
        client.flush().await.unwrap();
        let mut ack = [0u8; 64];
        let _ = client.read(&mut ack).await.unwrap();
        client
            .write_all(b"POST /v1/chat/completions HTTP/1.1\r\nHost: ai-api.jdcloud.com\r\ncontent-length:2\r\n\r\n{}")
            .await
            .unwrap();
        client.flush().await.unwrap();

        let mut out = Vec::new();
        client.read_to_end(&mut out).await.unwrap();

        assert!(String::from_utf8_lossy(&out).contains("ok"));
        assert!(
            seen.lock()
                .await
                .contains("Proxy-Authorization: Basic c2FuZGJveDplZ3Jlc3MtdG9rZW4=\r\n"),
            "bridge must inject Envoy route authentication"
        );
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
