use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, RwLock};
use std::time::Duration;

use axum::http::{header, StatusCode};
use axum::routing::get;
use axum::Json;
use axum::Router;
use k8s_openapi::api::core::v1::Pod;
use kube::api::{Patch, PatchParams};
use kube::{Api, Client};
use serde_json::json;
use sqlx::{Connection, PgConnection};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{info, warn};

use crate::config::JoySafeterConfig;
use crate::xds::status::{XdsRuntimeSnapshot, XdsRuntimeStatus};

pub const ACTIVE_POD_LABEL: &str = "joysafeter.io/control-plane-active";

fn active_pod_label_patch(active: bool) -> serde_json::Value {
    json!({
        "metadata": {
            "labels": {
                (ACTIVE_POD_LABEL): if active { "true" } else { "false" }
            }
        }
    })
}

pub async fn set_active_pod_label(instance_id: &str, active: bool) -> anyhow::Result<()> {
    let Ok(namespace) = std::env::var("JOYSAFETER_POD_NAMESPACE") else {
        return Ok(());
    };
    if namespace.trim().is_empty() {
        return Ok(());
    }

    let pods: Api<Pod> = Api::namespaced(Client::try_default().await?, namespace.trim());
    pods.patch(
        instance_id,
        &PatchParams::default(),
        &Patch::Merge(active_pod_label_patch(active)),
    )
    .await?;
    info!(
        instance_id,
        active, "Updated active control-plane Pod label"
    );
    Ok(())
}

#[derive(Clone, Default)]
pub struct ControlPlaneHealth {
    active: Arc<AtomicBool>,
    xds_status: Arc<RwLock<Option<XdsRuntimeStatus>>>,
}

impl ControlPlaneHealth {
    pub fn set_active(&self, active: bool) {
        self.active.store(active, Ordering::Release);
    }

    pub fn is_active(&self) -> bool {
        self.active.load(Ordering::Acquire)
    }

    pub fn attach_xds_status(&self, status: XdsRuntimeStatus) {
        *self.xds_status.write().expect("xDS health lock poisoned") = Some(status);
    }

    fn xds_snapshot(&self) -> Option<XdsRuntimeSnapshot> {
        self.xds_status
            .read()
            .expect("xDS health lock poisoned")
            .as_ref()
            .map(XdsRuntimeStatus::snapshot)
    }

    fn prometheus_metrics(&self) -> String {
        self.xds_status
            .read()
            .expect("xDS health lock poisoned")
            .as_ref()
            .cloned()
            .unwrap_or_default()
            .render_prometheus(self.is_active())
    }
}

pub async fn start_health_server(
    bind: &str,
    health: ControlPlaneHealth,
) -> anyhow::Result<JoinHandle<()>> {
    let listener = tokio::net::TcpListener::bind(bind).await?;
    let router = health_router(health);
    let bind = bind.to_string();
    Ok(tokio::spawn(async move {
        info!(address = %bind, "Control-plane health server started");
        if let Err(error) = axum::serve(listener, router).await {
            warn!(error = %error, "Control-plane health server stopped unexpectedly");
        }
    }))
}

fn health_router(health: ControlPlaneHealth) -> Router {
    let ready_health = health.clone();
    let xds_health = health.clone();
    let metrics_health = health.clone();
    Router::new()
        .route("/healthz", get(|| async { StatusCode::OK }))
        .route(
            "/ready",
            get(move || {
                let health = ready_health.clone();
                async move {
                    if health.is_active() {
                        StatusCode::OK
                    } else {
                        StatusCode::SERVICE_UNAVAILABLE
                    }
                }
            }),
        )
        .route(
            "/xds/status",
            get(move || {
                let health = xds_health.clone();
                async move {
                    let snapshot = health.xds_snapshot();
                    let status = if health.is_active() && snapshot.is_some() {
                        StatusCode::OK
                    } else {
                        StatusCode::SERVICE_UNAVAILABLE
                    };
                    (status, Json(snapshot.unwrap_or_default()))
                }
            }),
        )
        .route(
            "/metrics",
            get(move || {
                let health = metrics_health.clone();
                async move {
                    (
                        StatusCode::OK,
                        [(
                            header::CONTENT_TYPE,
                            "text/plain; version=0.0.4; charset=utf-8",
                        )],
                        health.prometheus_metrics(),
                    )
                }
            }),
        )
}

pub struct LeadershipGuard {
    lost: CancellationToken,
    monitor: Option<JoinHandle<()>>,
}

impl LeadershipGuard {
    pub async fn wait_lost(&self) {
        self.lost.cancelled().await;
    }

    pub async fn release(mut self) {
        if let Some(monitor) = self.monitor.take() {
            monitor.abort();
            let _ = monitor.await;
        }
    }
}

impl Drop for LeadershipGuard {
    fn drop(&mut self) {
        if let Some(monitor) = self.monitor.take() {
            monitor.abort();
        }
    }
}

pub async fn wait_for_active(
    config: &JoySafeterConfig,
    shutdown: CancellationToken,
) -> anyhow::Result<Option<LeadershipGuard>> {
    if shutdown.is_cancelled() {
        return Ok(None);
    }

    let lost = CancellationToken::new();
    if !config.control_plane_ha_enabled {
        info!("Control-plane HA disabled; this process is active");
        return Ok(Some(LeadershipGuard {
            lost,
            monitor: None,
        }));
    }

    let retry = Duration::from_millis(config.control_plane_standby_retry_ms.max(100));
    loop {
        let attempt = tokio::select! {
            _ = shutdown.cancelled() => return Ok(None),
            attempt = try_acquire_leadership(
                &config.database_url,
                config.control_plane_lock_key,
            ) => attempt,
        };
        match attempt {
            Ok(Some(connection)) => {
                info!(
                    instance_id = %config.instance_id,
                    lock_key = config.control_plane_lock_key,
                    "Acquired active control-plane leadership"
                );
                return Ok(Some(spawn_leadership_monitor(connection, config, lost)));
            }
            Ok(None) => {
                info!(
                    instance_id = %config.instance_id,
                    lock_key = config.control_plane_lock_key,
                    "Control-plane replica is cold standby"
                );
            }
            Err(error) => {
                warn!(error = %error, "Cold standby cannot query PostgreSQL leadership authority");
            }
        }
        tokio::select! {
            _ = shutdown.cancelled() => return Ok(None),
            _ = tokio::time::sleep(retry) => {}
        }
    }
}

async fn try_acquire_leadership(
    database_url: &str,
    lock_key: i64,
) -> Result<Option<PgConnection>, sqlx::Error> {
    let mut connection = PgConnection::connect(database_url).await?;
    let acquired: bool = sqlx::query_scalar("SELECT pg_try_advisory_lock($1)")
        .bind(lock_key)
        .fetch_one(&mut connection)
        .await?;
    Ok(acquired.then_some(connection))
}

fn spawn_leadership_monitor(
    mut connection: PgConnection,
    config: &JoySafeterConfig,
    lost: CancellationToken,
) -> LeadershipGuard {
    let interval = Duration::from_millis(config.control_plane_lock_probe_interval_ms.max(250));
    let timeout = Duration::from_millis(config.control_plane_lock_probe_timeout_ms.max(250));
    let monitor_lost = lost.clone();
    let instance_id = config.instance_id.clone();
    let monitor = tokio::spawn(async move {
        loop {
            tokio::time::sleep(interval).await;
            let probe = tokio::time::timeout(
                timeout,
                sqlx::query_scalar::<_, i32>("SELECT 1").fetch_one(&mut connection),
            )
            .await;
            match probe {
                Ok(Ok(1)) => {}
                Ok(Ok(value)) => {
                    warn!(instance_id = %instance_id, value, "Leadership probe returned an unexpected value");
                    monitor_lost.cancel();
                    return;
                }
                Ok(Err(error)) => {
                    warn!(instance_id = %instance_id, error = %error, "Leadership connection failed; relinquishing active role");
                    monitor_lost.cancel();
                    return;
                }
                Err(_) => {
                    warn!(instance_id = %instance_id, "Leadership probe timed out; relinquishing active role");
                    monitor_lost.cancel();
                    return;
                }
            }
        }
    });
    LeadershipGuard {
        lost,
        monitor: Some(monitor),
    }
}

#[cfg(test)]
mod tests {
    use std::env;
    use std::time::Duration;

    use crate::xds::status::{XdsRuntimeSnapshot, XdsRuntimeStatus};

    use super::{
        active_pod_label_patch, health_router, try_acquire_leadership, ControlPlaneHealth,
        ACTIVE_POD_LABEL,
    };

    #[test]
    fn active_pod_label_patch_uses_the_service_selector_key() {
        assert_eq!(
            active_pod_label_patch(true)["metadata"]["labels"][ACTIVE_POD_LABEL],
            "true"
        );
        assert_eq!(
            active_pod_label_patch(false)["metadata"]["labels"][ACTIVE_POD_LABEL],
            "false"
        );
    }

    #[test]
    fn readiness_tracks_only_active_role() {
        let health = ControlPlaneHealth::default();
        assert!(!health.is_active());
        health.set_active(true);
        assert!(health.is_active());
        health.set_active(false);
        assert!(!health.is_active());
    }

    #[test]
    fn xds_status_can_be_attached_after_health_startup() {
        let health = ControlPlaneHealth::default();
        assert!(health.xds_snapshot().is_none());
        let status = XdsRuntimeStatus::default();
        status.replace(XdsRuntimeSnapshot {
            connected_nodes: 2,
            ..XdsRuntimeSnapshot::default()
        });
        health.attach_xds_status(status);
        assert_eq!(health.xds_snapshot().unwrap().connected_nodes, 2);
        assert!(health
            .prometheus_metrics()
            .contains("joysafeter_control_plane_active 0"));
        health.set_active(true);
        assert!(health
            .prometheus_metrics()
            .contains("joysafeter_rust_xds_connected_nodes 2"));
    }

    #[tokio::test]
    async fn metrics_endpoint_serves_prometheus_text() {
        let health = ControlPlaneHealth::default();
        health.set_active(true);
        let status = XdsRuntimeStatus::default();
        status.record_ack();
        health.attach_xds_status(status);
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let server = tokio::spawn(async move {
            axum::serve(listener, health_router(health)).await.unwrap();
        });

        let response = reqwest::get(format!("http://{address}/metrics"))
            .await
            .unwrap();
        assert_eq!(response.status(), reqwest::StatusCode::OK);
        assert_eq!(
            response.headers()[reqwest::header::CONTENT_TYPE],
            "text/plain; version=0.0.4; charset=utf-8"
        );
        let body = response.text().await.unwrap();
        assert!(body.contains("joysafeter_control_plane_active 1"));
        assert!(body.contains("joysafeter_rust_xds_ack_total{result=\"ack\"} 1"));
        server.abort();
    }

    #[tokio::test]
    async fn postgres_lock_allows_one_active_and_clean_handoff() {
        let Some(database_url) = env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
        else {
            eprintln!("skipping active/standby PostgreSQL test: DATABASE_URL is not set");
            return;
        };
        let lock_key = rand::random::<i64>();

        let first = try_acquire_leadership(&database_url, lock_key)
            .await
            .expect("first leadership query")
            .expect("first replica must acquire leadership");
        let second = try_acquire_leadership(&database_url, lock_key)
            .await
            .expect("second leadership query");
        assert!(second.is_none(), "second replica must remain cold standby");

        drop(first);
        let deadline = tokio::time::Instant::now() + Duration::from_secs(2);
        loop {
            if let Some(successor) = try_acquire_leadership(&database_url, lock_key)
                .await
                .expect("leadership handoff query")
            {
                drop(successor);
                break;
            }
            assert!(
                tokio::time::Instant::now() < deadline,
                "standby did not acquire leadership after active connection closed"
            );
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    }
}
