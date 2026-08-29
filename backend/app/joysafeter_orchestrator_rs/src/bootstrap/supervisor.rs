use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use tracing::{info, warn};

use crate::xds;

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

pub(crate) fn spawn_health_server(
    port: u16,
    ready: Arc<AtomicBool>,
    xds_authority: xds::authority::XdsAuthority,
    xds_control_plane: Option<xds::control_plane::XdsControlPlane>,
) {
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
            let authority = xds_authority.clone();
            let control_plane = xds_control_plane.clone();
            tokio::spawn(async move {
                let mut buffer = [0u8; 512];
                let _ = tokio::io::AsyncReadExt::read(&mut stream, &mut buffer).await;
                let request = String::from_utf8_lossy(&buffer);
                let path = request
                    .lines()
                    .next()
                    .and_then(|line| line.split_whitespace().nth(1))
                    .unwrap_or("/");
                let (status, content_type, body) = match path {
                    "/healthz/ready" if ready.load(Ordering::Acquire) => {
                        ("200 OK", "text/plain; charset=utf-8", "ok".to_string())
                    }
                    "/healthz/ready" => (
                        "503 Service Unavailable",
                        "text/plain; charset=utf-8",
                        "standby".to_string(),
                    ),
                    "/healthz/live" => ("200 OK", "text/plain; charset=utf-8", "ok".to_string()),
                    "/healthz/xds" => {
                        let health = control_plane.as_ref().map_or(
                            xds::metrics::XdsHealthResponse {
                                status_code: 503,
                                body: "disabled",
                            },
                            |_| xds::metrics::xds_health(authority.phase()),
                        );
                        let status = if health.status_code == 200 {
                            "200 OK"
                        } else {
                            "503 Service Unavailable"
                        };
                        (status, "text/plain; charset=utf-8", health.body.to_string())
                    }
                    "/metrics" => {
                        let body = match control_plane {
                            Some(control_plane) => {
                                control_plane.metrics_snapshot().await.render_prometheus()
                            }
                            None => concat!(
                                "# HELP joysafeter_xds_enabled Whether the xDS control plane is enabled.\n",
                                "# TYPE joysafeter_xds_enabled gauge\n",
                                "joysafeter_xds_enabled 0\n"
                            )
                            .to_string(),
                        };
                        ("200 OK", "text/plain; version=0.0.4", body)
                    }
                    _ => (
                        "404 Not Found",
                        "text/plain; charset=utf-8",
                        "not found".to_string(),
                    ),
                };
                let response = format!(
                    "HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = stream.write_all(response.as_bytes()).await;
            });
        }
    });
}
