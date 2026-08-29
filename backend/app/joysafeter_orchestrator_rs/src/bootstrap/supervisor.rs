use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use tracing::{info, warn};

/// Wait for SIGINT or SIGTERM.
pub(crate) async fn shutdown_signal() {
    let ctrl_c = tokio::signal::ctrl_c();

    #[cfg(unix)]
    {
        let mut sigterm = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to register SIGTERM handler");
        tokio::select! {
            _ = ctrl_c => {},
            _ = sigterm.recv() => {},
        }
    }

    #[cfg(not(unix))]
    {
        ctrl_c.await.expect("failed to listen for Ctrl+C");
    }
}

/// Minimal HTTP health server for K8s readiness and liveness probes.
pub(crate) fn spawn_health_server(port: u16, ready: Arc<AtomicBool>) {
    use tokio::io::AsyncWriteExt;

    tokio::spawn(async move {
        let listener = match tokio::net::TcpListener::bind(("0.0.0.0", port)).await {
            Ok(listener) => listener,
            Err(error) => {
                warn!(port, error = %error, "Health server bind failed");
                return;
            }
        };
        info!(port, "Health server listening");
        loop {
            let Ok((mut stream, _)) = listener.accept().await else {
                continue;
            };
            let ready = ready.clone();
            tokio::spawn(async move {
                let mut buffer = [0u8; 512];
                let _ = tokio::io::AsyncReadExt::read(&mut stream, &mut buffer).await;
                let request = String::from_utf8_lossy(&buffer);
                let response = if request.contains("/healthz/ready") {
                    if ready.load(Ordering::Acquire) {
                        "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
                    } else {
                        "HTTP/1.1 503 Service Unavailable\r\nContent-Length: 7\r\n\r\nstandby"
                    }
                } else {
                    "HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"
                };
                let _ = stream.write_all(response.as_bytes()).await;
            });
        }
    });
}
