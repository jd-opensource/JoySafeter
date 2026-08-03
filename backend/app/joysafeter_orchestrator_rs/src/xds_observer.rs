use std::time::Duration;

use sha2::{Digest, Sha256};
use sqlx::PgPool;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;
use tracing::{debug, error, warn};
use uuid::Uuid;

use crate::sandbox::lds_backend::{XdsObservation, XdsObservationStatus, XdsObservationTransition};

pub fn spawn_shadow_observer(
    pool: PgPool,
    orchestrator_instance: String,
    mut observations: mpsc::UnboundedReceiver<XdsObservation>,
    shutdown: CancellationToken,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        let mut draining = false;
        loop {
            let observation = if draining {
                observations.try_recv().ok()
            } else {
                tokio::select! {
                    _ = shutdown.cancelled() => {
                        draining = true;
                        continue;
                    }
                    observation = observations.recv() => observation,
                }
            };
            let Some(observation) = observation else {
                return;
            };
            let mut retry_delay = Duration::from_millis(100);
            loop {
                match persist_observation(&pool, &orchestrator_instance, &observation).await {
                    Ok(()) => {
                        if observation.exchange {
                            match observation.status {
                                XdsObservationStatus::Ack => debug!(
                                    source_group = %observation.source_group_key,
                                    node_group = %observation.node_group_key,
                                    node = %observation.node_id,
                                    generation = observation.generation,
                                    type_url = %observation.type_url,
                                    "Persisted Rust xDS shadow ACK"
                                ),
                                XdsObservationStatus::Nack => warn!(
                                    source_group = %observation.source_group_key,
                                    node_group = %observation.node_group_key,
                                    node = %observation.node_id,
                                    generation = observation.generation,
                                    type_url = %observation.type_url,
                                    error = %observation.error_summary.as_deref().unwrap_or_default(),
                                    "Persisted Rust xDS shadow NACK"
                                ),
                            }
                        } else {
                            debug!(
                                source_group = %observation.source_group_key,
                                node_group = %observation.node_group_key,
                                generation = observation.generation,
                                transition = ?observation.transition,
                                "Persisted Rust xDS shadow lifecycle transition"
                            );
                        }
                        break;
                    }
                    Err(error) => error!(
                        source_group = %observation.source_group_key,
                        node_group = %observation.node_group_key,
                        node = %observation.node_id,
                        generation = observation.generation,
                        type_url = %observation.type_url,
                        %error,
                        retry_ms = retry_delay.as_millis(),
                        "Failed to persist Rust xDS shadow observation"
                    ),
                }
                if draining {
                    tokio::time::sleep(retry_delay).await;
                } else {
                    tokio::select! {
                        _ = shutdown.cancelled() => {
                            draining = true;
                        }
                        _ = tokio::time::sleep(retry_delay) => {}
                    }
                }
                retry_delay = (retry_delay * 2).min(Duration::from_secs(5));
            }
        }
    })
}

async fn persist_observation(
    pool: &PgPool,
    orchestrator_instance: &str,
    observation: &XdsObservation,
) -> anyhow::Result<()> {
    let mut transaction = pool.begin().await?;
    if observation.exchange {
        let status = match observation.status {
            XdsObservationStatus::Ack => "ack",
            XdsObservationStatus::Nack => "nack",
        };
        let nonce_sha256 = format!("{:x}", Sha256::digest(observation.nonce.as_bytes()));
        let error_summary = observation
            .error_summary
            .as_deref()
            .map(|summary| summary.chars().take(512).collect::<String>());
        sqlx::query(
            r#"
            INSERT INTO joysafeter_rust_xds_shadow_status (
              id, source_group_key, node_group_key, generation, node_id,
              type_url, xds_version, status, nonce_sha256,
              orchestrator_instance, error_code, error_summary, observed_at
            ) VALUES (
              $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, now()
            )
            ON CONFLICT (
              source_group_key, generation, node_group_key, node_id, type_url
            ) DO UPDATE SET
              xds_version = EXCLUDED.xds_version,
              status = EXCLUDED.status,
              nonce_sha256 = EXCLUDED.nonce_sha256,
              orchestrator_instance = EXCLUDED.orchestrator_instance,
              error_code = EXCLUDED.error_code,
              error_summary = EXCLUDED.error_summary,
              observed_at = now(),
              updated_at = now()
            WHERE joysafeter_rust_xds_shadow_status.status <> 'nack'
               OR EXCLUDED.status = 'nack'
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(&observation.source_group_key)
        .bind(&observation.node_group_key)
        .bind(observation.generation)
        .bind(&observation.node_id)
        .bind(&observation.type_url)
        .bind(&observation.xds_version)
        .bind(status)
        .bind(nonce_sha256)
        .bind(orchestrator_instance)
        .bind(observation.error_code)
        .bind(error_summary)
        .execute(&mut *transaction)
        .await?;
    }
    if observation.transition != XdsObservationTransition::None {
        let (
            state,
            rollback_version,
            required_type_urls,
            connected_nodes,
            required_acks,
            acked_acks,
        ) = match &observation.transition {
            XdsObservationTransition::Accepted => {
                let quorum = observation.quorum.as_ref().ok_or_else(|| {
                    anyhow::anyhow!("accepted xDS lifecycle transition requires quorum evidence")
                })?;
                (
                    "accepted",
                    None,
                    Some(serde_json::to_value(&quorum.required_type_urls)?),
                    Some(i32::try_from(quorum.connected_nodes)?),
                    Some(i32::try_from(quorum.required_acks)?),
                    Some(i32::try_from(quorum.acked_acks)?),
                )
            }
            XdsObservationTransition::RolledBack { rollback_version } => (
                "failed",
                Some(rollback_version.as_str()),
                None,
                None,
                None,
                None,
            ),
            XdsObservationTransition::None => unreachable!(),
        };
        sqlx::query(
            r#"
            INSERT INTO joysafeter_rust_xds_shadow_generations (
              id, source_group_key, node_group_key, generation, xds_version,
              state, rollback_version, orchestrator_instance,
              required_type_urls, connected_nodes, required_acks, acked_acks,
              accepted_at, failed_at
            ) VALUES (
              $1, $2, $3, $4, $5, $6, $7, $8,
              $9, $10, $11, $12,
              CASE WHEN $6 = 'accepted' THEN now() END,
              CASE WHEN $6 = 'failed' THEN now() END
            )
            ON CONFLICT (source_group_key, node_group_key, generation) DO UPDATE SET
              xds_version = EXCLUDED.xds_version,
              state = EXCLUDED.state,
              rollback_version = EXCLUDED.rollback_version,
              orchestrator_instance = EXCLUDED.orchestrator_instance,
              required_type_urls = EXCLUDED.required_type_urls,
              connected_nodes = EXCLUDED.connected_nodes,
              required_acks = EXCLUDED.required_acks,
              acked_acks = EXCLUDED.acked_acks,
              accepted_at = EXCLUDED.accepted_at,
              failed_at = EXCLUDED.failed_at,
              updated_at = now()
            WHERE joysafeter_rust_xds_shadow_generations.state <> 'failed'
               OR EXCLUDED.state = 'failed'
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(&observation.source_group_key)
        .bind(&observation.node_group_key)
        .bind(observation.generation)
        .bind(&observation.xds_version)
        .bind(state)
        .bind(rollback_version)
        .bind(orchestrator_instance)
        .bind(required_type_urls)
        .bind(connected_nodes)
        .bind(required_acks)
        .bind(acked_acks)
        .execute(&mut *transaction)
        .await?;
    }
    transaction.commit().await?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::env;

    use serde_json::json;
    use sqlx::postgres::PgPoolOptions;

    use super::*;
    use crate::sandbox::lds_backend::XdsQuorumEvidence;
    use crate::xds::snapshot::LISTENER_TYPE_URL;

    #[test]
    fn nonce_hash_is_stable_and_error_summary_is_bounded() {
        let nonce = "n-1-type-version";
        assert_eq!(
            format!("{:x}", Sha256::digest(nonce.as_bytes())),
            "1d17a1c8d61e253e9cb6389e0c09b0a66457ec001d5d4ebda60117598001df9e"
        );
        assert_eq!("界".repeat(600).chars().take(512).count(), 512);
    }

    #[tokio::test]
    async fn lifecycle_only_accept_persists_quorum_without_raw_ack() {
        let Some(database_url) = env::var("JOYSAFETER_TEST_DATABASE_URL")
            .ok()
            .or_else(|| env::var("DATABASE_URL").ok())
        else {
            eprintln!("skipping Rust xDS quorum persistence test: DATABASE_URL is not set");
            return;
        };
        let pool = PgPoolOptions::new()
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
            eprintln!("skipping Rust xDS quorum persistence test: migration is not installed");
            return;
        }
        let suffix = Uuid::now_v7().simple().to_string();
        let group_suffix = format!("{suffix}abcdefghijk");
        let source_group = format!("v1:{group_suffix}");
        let node_group = format!("v2:{group_suffix}");
        sqlx::query(
            r#"
            INSERT INTO joysafeter_egress_group_generations (
              id, group_key, generation, node_selector, policy_schema_version,
              desired_policies, content_sha256, state
            ) VALUES ($1, $2, 1, $3, 1, '[]'::jsonb, $4, 'desired')
            "#,
        )
        .bind(Uuid::now_v7())
        .bind(&source_group)
        .bind(json!({
            "deployment_id": "test",
            "environment": "test",
            "region": "local",
            "provider": "k8s",
            "shard_id": "0",
            "envoy_version": "1.39.0",
            "config_schema_version": "1"
        }))
        .bind("a".repeat(64))
        .execute(&pool)
        .await
        .unwrap();
        let observation = XdsObservation {
            exchange: false,
            source_group_key: source_group.clone(),
            node_group_key: node_group,
            node_id: "ack-disconnect".to_string(),
            generation: 1,
            type_url: String::new(),
            xds_version: "g1-test".to_string(),
            nonce: String::new(),
            status: XdsObservationStatus::Ack,
            error_code: None,
            error_summary: None,
            quorum: Some(XdsQuorumEvidence {
                connected_nodes: 1,
                required_type_urls: vec![LISTENER_TYPE_URL.to_string()],
                required_acks: 1,
                acked_acks: 1,
            }),
            transition: XdsObservationTransition::Accepted,
        };
        persist_observation(&pool, "orchestrator-test", &observation)
            .await
            .unwrap();

        let lifecycle: (i32, i32, i32) = sqlx::query_as(
            r#"
            SELECT connected_nodes, required_acks, acked_acks
            FROM joysafeter_rust_xds_shadow_generations
            WHERE source_group_key = $1 AND generation = 1
            "#,
        )
        .bind(&source_group)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(lifecycle, (1, 1, 1));
        let raw_count: i64 = sqlx::query_scalar(
            "SELECT count(*) FROM joysafeter_rust_xds_shadow_status WHERE source_group_key = $1",
        )
        .bind(&source_group)
        .fetch_one(&pool)
        .await
        .unwrap();
        assert_eq!(raw_count, 0);
        sqlx::query("DELETE FROM joysafeter_egress_group_generations WHERE group_key = $1")
            .bind(&source_group)
            .execute(&pool)
            .await
            .unwrap();
    }
}
