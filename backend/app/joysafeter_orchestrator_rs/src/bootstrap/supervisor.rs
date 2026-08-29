use tracing::info;

use crate::xds;

pub(crate) use super::managed_service::{ReadinessGate, ServiceCriticality, TaskSupervisor};

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

pub(crate) async fn spawn_health_server(
    port: u16,
    ready: ReadinessGate,
    xds_authority: xds::authority::XdsAuthority,
    xds_control_plane: Option<xds::control_plane::XdsControlPlane>,
) -> anyhow::Result<tokio::task::JoinHandle<()>> {
    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port)).await?;

    Ok(tokio::spawn(async move {
        use tokio::io::AsyncWriteExt;

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
                    "/healthz/ready" if ready.is_ready() => {
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
    }))
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::{ReadinessGate, ServiceCriticality, TaskSupervisor};

    #[tokio::test]
    async fn readiness_stays_false_until_bootstrap_marks_it_ready() {
        let readiness = ReadinessGate::new();

        assert!(!readiness.is_ready());
        readiness.mark_ready();
        assert!(readiness.is_ready());
        readiness.mark_not_ready();
        assert!(!readiness.is_ready());
    }

    #[tokio::test]
    async fn critical_task_exit_marks_application_not_ready() {
        let readiness = ReadinessGate::new();
        let mut supervisor = TaskSupervisor::new(readiness.clone());
        supervisor
            .register(
                "critical",
                ServiceCriticality::Critical,
                tokio::spawn(async {}),
            )
            .expect("register critical service");
        supervisor.seal_startup();

        let exit =
            tokio::time::timeout(Duration::from_secs(1), supervisor.wait_for_critical_exit())
                .await
                .expect("critical exit must be observed");

        assert_eq!(exit.service_name(), "critical");
        assert!(!readiness.is_ready());
    }

    #[tokio::test]
    async fn degradable_task_exit_does_not_mark_application_not_ready() {
        let readiness = ReadinessGate::new();
        let mut supervisor = TaskSupervisor::new(readiness.clone());
        supervisor
            .register(
                "degradable",
                ServiceCriticality::Degradable,
                tokio::spawn(async {}),
            )
            .expect("register degradable service");
        supervisor.seal_startup();

        tokio::time::sleep(Duration::from_millis(20)).await;

        assert!(readiness.is_ready());
        assert!(tokio::time::timeout(
            Duration::from_millis(20),
            supervisor.wait_for_critical_exit(),
        )
        .await
        .is_err());
    }

    #[tokio::test]
    async fn health_server_bind_failure_is_reported_to_bootstrap() {
        let occupied = tokio::net::TcpListener::bind(("0.0.0.0", 0))
            .await
            .expect("reserve local port");
        let port = occupied.local_addr().expect("reserved address").port();

        let result = super::spawn_health_server(
            port,
            ReadinessGate::new(),
            crate::xds::authority::XdsAuthority::standalone(),
            None,
        )
        .await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn intentional_service_abort_does_not_report_a_critical_failure() {
        let readiness = ReadinessGate::new();
        let mut supervisor = TaskSupervisor::new(readiness.clone());
        let scheduler = supervisor
            .register(
                "scheduler",
                ServiceCriticality::Critical,
                tokio::spawn(std::future::pending()),
            )
            .expect("register scheduler");
        scheduler.mark_ready();
        supervisor.seal_startup();

        assert!(supervisor.abort("scheduler"));
        tokio::time::sleep(Duration::from_millis(20)).await;

        assert!(readiness.is_ready());
        assert!(tokio::time::timeout(
            Duration::from_millis(20),
            supervisor.wait_for_critical_exit(),
        )
        .await
        .is_err());
    }
}
