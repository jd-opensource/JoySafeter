use sha2::{Digest, Sha256};
use sqlx::PgPool;
use tracing::{debug, error, warn};
use uuid::Uuid;

use crate::ids::{MemoryId, MemoryStoreId, MemoryVersionId, SessionId};

pub(crate) async fn handle_memory_sync_db(
    pool: &PgPool,
    session_id: Option<SessionId>,
    store_mount_name: &str,
    relative_path: &str,
    content: &str,
    operation: &str,
    max_memories_per_store: i64,
) {
    // Path traversal protection
    let normalized = relative_path.replace('\\', "/");
    if normalized.contains("..") || normalized.contains('\0') {
        warn!(
            path = relative_path,
            "Path traversal attempt in memory sync, rejecting"
        );
        return;
    }

    let session_id = match session_id {
        Some(sid) => sid,
        None => return,
    };

    // Normalize path to start with /
    let norm_path = if normalized.starts_with('/') {
        normalized
    } else {
        format!("/{normalized}")
    };

    // Resolve store from mount_name → store_id
    let store = match sqlx::query_as::<_, (MemoryStoreId, String)>(
        r#"
        SELECT sms.store_id, sms.access
        FROM joysafeter_session_memory_stores sms
        WHERE sms.session_id = $1 AND sms.mount_name = $2
        LIMIT 1
        "#,
    )
    .bind(session_id)
    .bind(store_mount_name)
    .fetch_optional(pool)
    .await
    {
        Ok(Some(s)) => s,
        Ok(None) => {
            debug!(
                mount = store_mount_name,
                "Memory store not found for session"
            );
            return;
        }
        Err(e) => {
            error!("Memory sync store lookup failed: {e}");
            return;
        }
    };

    let (store_id, access) = store;

    // Check read-only
    if access == "read_only" {
        warn!(
            store = store_mount_name,
            "Rejecting write to read-only memory store"
        );
        return;
    }

    let mut tx = match pool.begin().await {
        Ok(tx) => tx,
        Err(e) => {
            error!(error = %e, "Memory sync transaction start failed");
            return;
        }
    };

    let archived_at = match sqlx::query_scalar::<_, Option<chrono::DateTime<chrono::Utc>>>(
        "SELECT archived_at FROM joysafeter_memory_stores WHERE id = $1 FOR UPDATE",
    )
    .bind(store_id)
    .fetch_optional(&mut *tx)
    .await
    {
        Ok(Some(archived_at)) => archived_at,
        Ok(None) => {
            warn!(store_id = %store_id, "Memory store missing during sync");
            return;
        }
        Err(e) => {
            error!(error = %e, "Memory store lock failed");
            return;
        }
    };
    if archived_at.is_some() {
        warn!(
            store_id = %store_id,
            store = store_mount_name,
            "Rejecting write to archived memory store"
        );
        return;
    }

    match operation {
        "delete" => {
            let existing = match sqlx::query_as::<_, (MemoryId,)>(
                r#"
                SELECT id FROM joysafeter_memories
                WHERE store_id = $1 AND path = $2
                LIMIT 1
                "#,
            )
            .bind(store_id)
            .bind(&norm_path)
            .fetch_optional(&mut *tx)
            .await
            {
                Ok(row) => row,
                Err(e) => {
                    error!(error = %e, "Memory delete lookup failed");
                    return;
                }
            };

            let Some((memory_id,)) = existing else {
                let _ = tx.commit().await;
                return;
            };

            let version_id = MemoryVersionId::from_uuid(Uuid::now_v7());
            if let Err(e) = sqlx::query(
                r#"
                INSERT INTO joysafeter_memory_versions
                    (id, store_id, memory_id, operation, path, content, content_sha256,
                     content_size_bytes, session_id, api_key_id, created_at)
                VALUES ($1, $2, $3, 'deleted', $4, NULL, NULL, NULL, $5, NULL, NOW())
                "#,
            )
            .bind(version_id)
            .bind(store_id)
            .bind(memory_id)
            .bind(&norm_path)
            .bind(session_id)
            .execute(&mut *tx)
            .await
            {
                error!(error = %e, "Memory delete version insert failed");
                return;
            }

            if let Err(e) =
                sqlx::query("DELETE FROM joysafeter_memories WHERE store_id = $1 AND id = $2")
                    .bind(store_id)
                    .bind(memory_id)
                    .execute(&mut *tx)
                    .await
            {
                error!(error = %e, "Memory delete failed");
                return;
            }

            if let Err(e) = tx.commit().await {
                error!(error = %e, "Memory delete transaction commit failed");
                return;
            }

            debug!(
                store = store_mount_name,
                path = norm_path,
                "Memory file deleted"
            );
        }
        _ => {
            let content_bytes = content.as_bytes();
            let size = content_bytes.len() as i64;
            let sha = hex::encode(Sha256::digest(content_bytes));

            let existing = match sqlx::query_as::<_, (MemoryId, String)>(
                r#"
                SELECT id, content_sha256 FROM joysafeter_memories
                WHERE store_id = $1 AND path = $2
                LIMIT 1
                "#,
            )
            .bind(store_id)
            .bind(&norm_path)
            .fetch_optional(&mut *tx)
            .await
            {
                Ok(row) => row,
                Err(e) => {
                    error!(error = %e, "Memory upsert lookup failed");
                    return;
                }
            };

            if let Some((memory_id, existing_sha)) = existing {
                if existing_sha == sha {
                    let _ = tx.commit().await;
                    return;
                }

                let version_id = MemoryVersionId::from_uuid(Uuid::now_v7());
                if let Err(e) = sqlx::query(
                    r#"
                    INSERT INTO joysafeter_memory_versions
                        (id, store_id, memory_id, operation, path, content, content_sha256,
                         content_size_bytes, session_id, api_key_id, created_at)
                    VALUES ($1, $2, $3, 'modified', $4, $5, $6, $7, $8, NULL, NOW())
                    "#,
                )
                .bind(version_id)
                .bind(store_id)
                .bind(memory_id)
                .bind(&norm_path)
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(session_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory modified version insert failed");
                    return;
                }

                if let Err(e) = sqlx::query(
                    r#"
                    UPDATE joysafeter_memories
                    SET content = $1,
                        content_sha256 = $2,
                        size_bytes = $3,
                        version = COALESCE(version, 1) + 1,
                        current_version_id = $4,
                        updated_at = NOW()
                    WHERE store_id = $5 AND id = $6
                    "#,
                )
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(version_id)
                .bind(store_id)
                .bind(memory_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory update failed");
                    return;
                }
            } else {
                let count = match sqlx::query_as::<_, (i64,)>(
                    "SELECT COUNT(*) FROM joysafeter_memories WHERE store_id = $1",
                )
                .bind(store_id)
                .fetch_one(&mut *tx)
                .await
                {
                    Ok((count,)) => count,
                    Err(e) => {
                        error!(error = %e, "Memory count lookup failed");
                        return;
                    }
                };

                if count >= max_memories_per_store {
                    warn!(
                        store = store_mount_name,
                        limit = max_memories_per_store,
                        "Rejecting memory create because store limit was reached"
                    );
                    return;
                }

                let memory_id = MemoryId::from_uuid(Uuid::now_v7());
                let version_id = MemoryVersionId::from_uuid(Uuid::now_v7());
                if let Err(e) = sqlx::query(
                    r#"
                    INSERT INTO joysafeter_memory_versions
                        (id, store_id, memory_id, operation, path, content, content_sha256,
                         content_size_bytes, session_id, api_key_id, created_at)
                    VALUES ($1, $2, $3, 'created', $4, $5, $6, $7, $8, NULL, NOW())
                    "#,
                )
                .bind(version_id)
                .bind(store_id)
                .bind(memory_id)
                .bind(&norm_path)
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(session_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory created version insert failed");
                    return;
                }

                if let Err(e) = sqlx::query(
                    r#"
                    INSERT INTO joysafeter_memories
                        (id, store_id, path, content, content_sha256, size_bytes,
                         version, current_version_id, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, 1, $7, NOW(), NOW())
                    "#,
                )
                .bind(memory_id)
                .bind(store_id)
                .bind(&norm_path)
                .bind(content)
                .bind(&sha)
                .bind(size as i32)
                .bind(version_id)
                .execute(&mut *tx)
                .await
                {
                    error!(error = %e, "Memory create failed");
                    return;
                }
            }

            if let Err(e) = tx.commit().await {
                error!(error = %e, "Memory upsert transaction commit failed");
                return;
            }

            debug!(
                store = store_mount_name,
                path = norm_path,
                "Memory file upserted"
            );
        }
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
