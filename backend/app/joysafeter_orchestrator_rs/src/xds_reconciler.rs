use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use chrono::Utc;
use serde_json::Value;
use sqlx::postgres::PgListener;
use sqlx::PgPool;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, info, warn};
use uuid::Uuid;

use crate::sandbox::lds_backend::DeltaXdsServer;
use crate::xds::compiler::{compile_kubernetes, CompileInput, CompilerConfig};
use crate::xds::snapshot::CompiledSnapshot;

const GENERATION_NOTIFICATION_CHANNEL: &str = "joysafeter_egress_generation";

#[derive(Debug, Clone)]
struct DesiredGeneration {
    source_group_key: String,
    generation: i64,
    policy_schema_version: i32,
    desired_policies: Value,
    content_sha256: String,
    nacked: bool,
}

#[derive(Debug, Clone)]
struct AcceptedGeneration {
    node_group_key: String,
    generation: DesiredGeneration,
}

#[derive(Debug, Default, PartialEq, Eq)]
struct ReconcileStats {
    desired_groups: usize,
    node_snapshots: usize,
    changed_snapshots: usize,
    restored_snapshots: usize,
    skipped_groups: usize,
    quarantined_groups: usize,
    failed_snapshots: usize,
}

pub fn spawn_shadow_reconciler(
    pool: PgPool,
    xds: Arc<DeltaXdsServer>,
    compiler_config: CompilerConfig,
    interval: Duration,
    ack_timeout: Duration,
    orchestrator_instance: String,
    node_lease_ttl: Duration,
    shutdown: CancellationToken,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let (signals, mut signal_rx) = mpsc::channel(1);
        let listener_handle = tokio::spawn(listen_for_generations(
            pool.clone(),
            signals,
            shutdown.clone(),
        ));
        let mut node_groups = xds.subscribe_node_groups();
        let mut ticker = tokio::time::interval_at(tokio::time::Instant::now() + interval, interval);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
        let ack_check_interval = ack_timeout
            .min(Duration::from_secs(1))
            .max(Duration::from_millis(100));
        let mut ack_ticker = tokio::time::interval_at(
            tokio::time::Instant::now() + ack_check_interval,
            ack_check_interval,
        );
        ack_ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);

        run_reconcile(
            "startup",
            &pool,
            &xds,
            &compiler_config,
            &orchestrator_instance,
            node_lease_ttl,
        )
        .await;
        loop {
            let reason = tokio::select! {
                _ = shutdown.cancelled() => break,
                _ = ack_ticker.tick() => {
                    xds.expire_candidates(ack_timeout).await;
                    continue;
                }
                _ = ticker.tick() => "periodic",
                signal = signal_rx.recv() => {
                    if signal.is_none() {
                        break;
                    }
                    "notification"
                }
                changed = node_groups.changed() => {
                    if changed.is_err() {
                        break;
                    }
                    "node_lease"
                }
            };
            run_reconcile(
                reason,
                &pool,
                &xds,
                &compiler_config,
                &orchestrator_instance,
                node_lease_ttl,
            )
            .await;
        }

        listener_handle.abort();
        debug!("Rust xDS shadow reconciler stopped");
    })
}

async fn run_reconcile(
    reason: &'static str,
    pool: &PgPool,
    xds: &DeltaXdsServer,
    compiler_config: &CompilerConfig,
    orchestrator_instance: &str,
    node_lease_ttl: Duration,
) {
    match reconcile_all(
        pool,
        xds,
        compiler_config,
        orchestrator_instance,
        node_lease_ttl,
    )
    .await
    {
        Ok(stats) if stats.failed_snapshots > 0 => {
            xds.runtime_status().record_reconcile_failed();
            warn!(
                reason,
                desired_groups = stats.desired_groups,
                node_snapshots = stats.node_snapshots,
                changed_snapshots = stats.changed_snapshots,
                restored_snapshots = stats.restored_snapshots,
                skipped_groups = stats.skipped_groups,
                quarantined_groups = stats.quarantined_groups,
                failed_snapshots = stats.failed_snapshots,
                "Rust xDS shadow reconciliation completed with failures"
            );
        }
        Ok(stats) if stats.changed_snapshots > 0 || stats.restored_snapshots > 0 => {
            xds.runtime_status().record_reconcile_changed();
            info!(
                reason,
                desired_groups = stats.desired_groups,
                node_snapshots = stats.node_snapshots,
                changed_snapshots = stats.changed_snapshots,
                restored_snapshots = stats.restored_snapshots,
                skipped_groups = stats.skipped_groups,
                quarantined_groups = stats.quarantined_groups,
                "Rust xDS shadow snapshots updated"
            );
        }
        Ok(stats) => {
            xds.runtime_status().record_reconcile_unchanged();
            debug!(
                reason,
                desired_groups = stats.desired_groups,
                node_snapshots = stats.node_snapshots,
                restored_snapshots = stats.restored_snapshots,
                skipped_groups = stats.skipped_groups,
                quarantined_groups = stats.quarantined_groups,
                "Rust xDS shadow reconciliation unchanged"
            );
        }
        Err(error) => {
            xds.runtime_status().record_reconcile_failed();
            error!(
                reason,
                %error,
                "Rust xDS shadow reconciliation failed; current snapshots retained"
            );
        }
    }
}

async fn reconcile_all(
    pool: &PgPool,
    xds: &DeltaXdsServer,
    compiler_config: &CompilerConfig,
    orchestrator_instance: &str,
    node_lease_ttl: Duration,
) -> anyhow::Result<ReconcileStats> {
    sync_node_leases(pool, xds, orchestrator_instance, node_lease_ttl).await?;
    let desired = load_desired_generations(pool).await?;
    let accepted = load_accepted_generations(pool).await?;
    reconcile_desired(desired, accepted, xds, compiler_config).await
}

async fn sync_node_leases(
    pool: &PgPool,
    xds: &DeltaXdsServer,
    orchestrator_instance: &str,
    node_lease_ttl: Duration,
) -> anyhow::Result<()> {
    let leases = xds.node_lease_snapshots().await;
    let sync_token = Uuid::now_v7();
    let now = Utc::now();
    let lease_expires_at = now
        + chrono::Duration::from_std(node_lease_ttl).context("convert Rust xDS node lease TTL")?;
    let mut transaction = pool.begin().await?;
    for lease in leases {
        sqlx::query(
            r#"
            INSERT INTO joysafeter_rust_xds_shadow_node_connections (
              id, source_group_key, node_group_key, node_id,
              orchestrator_instance, sync_token, connected_at,
              last_seen_at, lease_expires_at, disconnected_at
            ) VALUES (
              $1, $2, $3, $4, $5, $6, $7, $7, $8, NULL
            )
            ON CONFLICT (node_group_key, node_id) DO UPDATE SET
              source_group_key = EXCLUDED.source_group_key,
              orchestrator_instance = EXCLUDED.orchestrator_instance,
              sync_token = EXCLUDED.sync_token,
              connected_at = CASE
                WHEN joysafeter_rust_xds_shadow_node_connections.disconnected_at IS NULL
                 AND joysafeter_rust_xds_shadow_node_connections.orchestrator_instance = EXCLUDED.orchestrator_instance
                THEN joysafeter_rust_xds_shadow_node_connections.connected_at
                ELSE EXCLUDED.connected_at
              END,
              last_seen_at = EXCLUDED.last_seen_at,
              lease_expires_at = EXCLUDED.lease_expires_at,
              disconnected_at = NULL,
              updated_at = now()
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(&lease.source_group_key)
        .bind(&lease.node_group_key)
        .bind(&lease.node_id)
        .bind(orchestrator_instance)
        .bind(sync_token)
        .bind(now)
        .bind(lease_expires_at)
        .execute(&mut *transaction)
        .await?;
    }
    sqlx::query(
        r#"
        UPDATE joysafeter_rust_xds_shadow_node_connections
        SET disconnected_at = now(), lease_expires_at = now(), updated_at = now()
        WHERE orchestrator_instance = $1
          AND sync_token <> $2
          AND disconnected_at IS NULL
        "#,
    )
    .bind(orchestrator_instance)
    .bind(sync_token)
    .execute(&mut *transaction)
    .await?;
    transaction.commit().await?;
    Ok(())
}

async fn load_desired_generations(pool: &PgPool) -> anyhow::Result<Vec<DesiredGeneration>> {
    let rows = sqlx::query_as::<_, (String, i64, i32, Value, String, bool)>(
        r#"
        SELECT DISTINCT ON (generation.group_key)
          generation.group_key,
          generation.generation,
          generation.policy_schema_version,
          generation.desired_policies,
          generation.content_sha256,
          EXISTS (
            SELECT 1
            FROM joysafeter_rust_xds_shadow_generations AS shadow
            WHERE shadow.source_group_key = generation.group_key
              AND shadow.generation = generation.generation
              AND shadow.state = 'failed'
          ) AS nacked
        FROM joysafeter_egress_group_generations AS generation
        WHERE generation.state = 'desired'
        ORDER BY generation.group_key, generation.generation DESC
        "#,
    )
    .fetch_all(pool)
    .await
    .context("query desired egress generations for Rust xDS shadow")?;

    Ok(rows
        .into_iter()
        .map(
            |(
                source_group_key,
                generation,
                policy_schema_version,
                desired_policies,
                content_sha256,
                nacked,
            )| DesiredGeneration {
                source_group_key,
                generation,
                policy_schema_version,
                desired_policies,
                content_sha256,
                nacked,
            },
        )
        .collect())
}

async fn load_accepted_generations(pool: &PgPool) -> anyhow::Result<Vec<AcceptedGeneration>> {
    let rows = sqlx::query_as::<_, (String, String, i64, i32, Value, String)>(
        r#"
        SELECT DISTINCT ON (lifecycle.source_group_key, lifecycle.node_group_key)
          lifecycle.source_group_key,
          lifecycle.node_group_key,
          generation.generation,
          generation.policy_schema_version,
          generation.desired_policies,
          generation.content_sha256
        FROM joysafeter_rust_xds_shadow_generations AS lifecycle
        JOIN joysafeter_egress_group_generations AS generation
          ON generation.group_key = lifecycle.source_group_key
         AND generation.generation = lifecycle.generation
        WHERE lifecycle.state = 'accepted'
        ORDER BY lifecycle.source_group_key, lifecycle.node_group_key,
                 generation.generation DESC
        "#,
    )
    .fetch_all(pool)
    .await
    .context("query accepted Rust xDS shadow generations")?;

    Ok(rows
        .into_iter()
        .map(
            |(
                source_group_key,
                node_group_key,
                generation,
                policy_schema_version,
                desired_policies,
                content_sha256,
            )| AcceptedGeneration {
                node_group_key,
                generation: DesiredGeneration {
                    source_group_key,
                    generation,
                    policy_schema_version,
                    desired_policies,
                    content_sha256,
                    nacked: false,
                },
            },
        )
        .collect())
}

async fn reconcile_desired(
    desired: Vec<DesiredGeneration>,
    accepted: Vec<AcceptedGeneration>,
    xds: &DeltaXdsServer,
    compiler_config: &CompilerConfig,
) -> anyhow::Result<ReconcileStats> {
    let mut stats = ReconcileStats {
        desired_groups: desired.len(),
        ..ReconcileStats::default()
    };
    let accepted = accepted
        .into_iter()
        .map(|accepted| {
            (
                (
                    accepted.generation.source_group_key.clone(),
                    accepted.node_group_key.clone(),
                ),
                accepted.generation,
            )
        })
        .collect::<HashMap<_, _>>();

    for generation in desired {
        if generation.nacked {
            stats.quarantined_groups += 1;
            warn!(
                source_group = %generation.source_group_key,
                generation = generation.generation,
                "Skipping persistently NACKed Rust xDS shadow generation"
            );
        }
        let node_groups = xds
            .node_groups_for_source(&generation.source_group_key)
            .await;
        if node_groups.is_empty() {
            stats.skipped_groups += 1;
            debug!(
                source_group = %generation.source_group_key,
                generation = generation.generation,
                "No connected node-local Envoy for desired xDS group"
            );
            continue;
        }

        for node_group_key in &node_groups {
            let key = (generation.source_group_key.clone(), node_group_key.clone());
            let Some(last_good) = accepted.get(&key) else {
                continue;
            };
            let restored = match compile_for_node(compiler_config, last_good, node_group_key) {
                Ok(snapshot) => xds.restore_snapshot(snapshot).await,
                Err(error) => Err(error),
            };
            match restored {
                Ok(true) => stats.restored_snapshots += 1,
                Ok(false) => {}
                Err(error) => {
                    stats.failed_snapshots += 1;
                    error!(
                        source_group = %generation.source_group_key,
                        node_group = %node_group_key,
                        generation = last_good.generation,
                        %error,
                        "Failed to restore Rust xDS last-known-good snapshot"
                    );
                }
            }
        }

        if generation.nacked {
            continue;
        }

        for node_group_key in node_groups {
            stats.node_snapshots += 1;
            let snapshot = match compile_for_node(compiler_config, &generation, &node_group_key) {
                Ok(snapshot) => snapshot,
                Err(error) => {
                    stats.failed_snapshots += 1;
                    error!(
                        source_group = %generation.source_group_key,
                        node_group = %node_group_key,
                        generation = generation.generation,
                        %error,
                        "Failed to compile Rust xDS shadow snapshot"
                    );
                    continue;
                }
            };
            match xds.install_snapshot(snapshot).await {
                Ok(true) => stats.changed_snapshots += 1,
                Ok(false) => {}
                Err(error) => {
                    stats.failed_snapshots += 1;
                    error!(
                        source_group = %generation.source_group_key,
                        node_group = %node_group_key,
                        generation = generation.generation,
                        %error,
                        "Failed to install Rust xDS shadow snapshot"
                    );
                }
            }
        }
    }
    Ok(stats)
}

fn compile_for_node(
    compiler_config: &CompilerConfig,
    desired: &DesiredGeneration,
    node_group_key: &str,
) -> anyhow::Result<CompiledSnapshot> {
    anyhow::ensure!(desired.generation > 0, "egress generation must be positive");
    let desired_policy_bytes = serde_json::to_vec(&desired.desired_policies)
        .context("serialize desired egress policy JSON")?;
    compile_kubernetes(
        compiler_config,
        CompileInput {
            group_key: node_group_key,
            generation: desired.generation,
            content_sha256: &desired.content_sha256,
            policy_schema_version: desired.policy_schema_version,
            desired_policies: &desired_policy_bytes,
        },
    )
}

async fn listen_for_generations(
    pool: PgPool,
    signals: mpsc::Sender<()>,
    shutdown: CancellationToken,
) {
    let mut reconnect_delay = Duration::from_millis(100);
    loop {
        if shutdown.is_cancelled() {
            return;
        }
        match PgListener::connect_with(&pool).await {
            Ok(mut listener) => {
                if let Err(error) = listener.listen(GENERATION_NOTIFICATION_CHANNEL).await {
                    warn!(%error, "Failed to subscribe Rust xDS generation listener");
                } else {
                    reconnect_delay = Duration::from_millis(100);
                    let _ = signals.try_send(());
                    loop {
                        tokio::select! {
                            _ = shutdown.cancelled() => return,
                            notification = listener.recv() => match notification {
                                Ok(_) => {
                                    let _ = signals.try_send(());
                                }
                                Err(error) => {
                                    warn!(%error, "Rust xDS generation listener disconnected");
                                    break;
                                }
                            }
                        }
                    }
                }
            }
            Err(error) => warn!(%error, "Failed to connect Rust xDS generation listener"),
        }
        tokio::select! {
            _ = shutdown.cancelled() => return,
            _ = tokio::time::sleep(reconnect_delay) => {}
        }
        reconnect_delay = (reconnect_delay * 2).min(Duration::from_secs(5));
    }
}

#[cfg(test)]
mod tests {
    use std::env;

    use super::*;

    const DIGEST: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

    fn fixture_desired() -> DesiredGeneration {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../../../egress-controller/testdata/compiler/parity-kubernetes-v1.json"
        ))
        .unwrap();
        DesiredGeneration {
            source_group_key: "v1:shared".to_string(),
            generation: fixture["generation"].as_i64().unwrap(),
            policy_schema_version: fixture["policy_schema_version"].as_i64().unwrap() as i32,
            desired_policies: fixture["policies"].clone(),
            content_sha256: DIGEST.to_string(),
            nacked: false,
        }
    }

    #[test]
    fn compiles_same_desired_generation_for_node_local_group() {
        let desired = fixture_desired();
        let snapshot =
            compile_for_node(&CompilerConfig::default(), &desired, "v2:node-local-a").unwrap();

        assert_eq!(snapshot.group_key, "v2:node-local-a");
        assert_eq!(snapshot.generation, 42);
        assert_eq!(snapshot.version, format!("g42-{}", &DIGEST[..32]));
    }

    #[tokio::test]
    async fn skips_desired_group_until_node_lease_exists() {
        let stats = reconcile_desired(
            vec![fixture_desired()],
            vec![],
            &DeltaXdsServer::new_node_local(),
            &CompilerConfig::default(),
        )
        .await
        .unwrap();

        assert_eq!(
            stats,
            ReconcileStats {
                desired_groups: 1,
                skipped_groups: 1,
                ..ReconcileStats::default()
            }
        );
    }

    #[tokio::test]
    async fn skips_persistently_nacked_generation_after_restart() {
        let mut desired = fixture_desired();
        desired.nacked = true;
        let stats = reconcile_desired(
            vec![desired],
            vec![],
            &DeltaXdsServer::new_node_local(),
            &CompilerConfig::default(),
        )
        .await
        .unwrap();

        assert_eq!(
            stats,
            ReconcileStats {
                desired_groups: 1,
                skipped_groups: 1,
                quarantined_groups: 1,
                ..ReconcileStats::default()
            }
        );
    }

    #[tokio::test]
    async fn restores_accepted_snapshot_before_skipping_failed_desired() {
        let server = DeltaXdsServer::new_node_local();
        server
            .register_test_node_group("v1:shared", "v2:node-a", "envoy-a")
            .await;
        let mut desired = fixture_desired();
        desired.nacked = true;
        let mut last_good = fixture_desired();
        last_good.generation = 41;
        let stats = reconcile_desired(
            vec![desired],
            vec![AcceptedGeneration {
                node_group_key: "v2:node-a".to_string(),
                generation: last_good,
            }],
            &server,
            &CompilerConfig::default(),
        )
        .await
        .unwrap();

        assert_eq!(
            stats,
            ReconcileStats {
                desired_groups: 1,
                restored_snapshots: 1,
                quarantined_groups: 1,
                ..ReconcileStats::default()
            }
        );
    }

    #[tokio::test]
    async fn postgres_node_lease_sync_marks_missing_streams_disconnected() {
        let Some(database_url) = env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
        else {
            eprintln!("skipping Rust xDS lease sync test: DATABASE_URL is not set");
            return;
        };
        let pool = sqlx::postgres::PgPoolOptions::new()
            .max_connections(2)
            .connect(&database_url)
            .await
            .unwrap();
        let table_exists: bool = sqlx::query_scalar(
            "SELECT to_regclass('joysafeter_rust_xds_shadow_node_connections') IS NOT NULL",
        )
        .fetch_one(&pool)
        .await
        .unwrap();
        if !table_exists {
            eprintln!("skipping Rust xDS lease sync test: migration is not installed");
            return;
        }
        let suffix = Uuid::now_v7().simple().to_string();
        let instance = format!("orchestrator-test-{suffix}");
        let node_group = format!("v2:{suffix}");
        let node_id = format!("envoy-{suffix}");
        let server = DeltaXdsServer::new_node_local();
        server
            .register_test_node_group("v1:test", &node_group, &node_id)
            .await;

        sync_node_leases(&pool, &server, &instance, Duration::from_secs(30))
            .await
            .unwrap();
        let connected: (String, bool, bool) = sqlx::query_as(
            r#"
            SELECT orchestrator_instance,
                   lease_expires_at > last_seen_at,
                   disconnected_at IS NULL
            FROM joysafeter_rust_xds_shadow_node_connections
            WHERE node_group_key = $1 AND node_id = $2
            "#,
        )
        .bind(&node_group)
        .bind(&node_id)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(connected, (instance.clone(), true, true));

        sync_node_leases(
            &pool,
            &DeltaXdsServer::new_node_local(),
            &instance,
            Duration::from_secs(30),
        )
        .await
        .unwrap();
        let disconnected: bool = sqlx::query_scalar(
            r#"
            SELECT disconnected_at IS NOT NULL
            FROM joysafeter_rust_xds_shadow_node_connections
            WHERE node_group_key = $1 AND node_id = $2
            "#,
        )
        .bind(&node_group)
        .bind(&node_id)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert!(disconnected);
        sqlx::query(
            "DELETE FROM joysafeter_rust_xds_shadow_node_connections WHERE orchestrator_instance = $1",
        )
        .bind(&instance)
        .execute(&pool)
        .await
        .unwrap();
    }
}
