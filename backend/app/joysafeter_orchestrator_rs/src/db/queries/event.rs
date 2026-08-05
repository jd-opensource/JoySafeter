use sqlx::PgPool;
use uuid::Uuid;

// ---------------------------------------------------------------------------
// Session event queries
// ---------------------------------------------------------------------------

/// Insert a batch of session events.
pub async fn batch_insert_events(
    pool: &PgPool,
    events: &[(Uuid, Uuid, &str, Option<&serde_json::Value>, Option<i64>)],
) -> Result<u64, sqlx::Error> {
    if events.is_empty() {
        return Ok(0);
    }

    let mut total = 0u64;
    for (id, session_id, event_type, payload, seq) in events {
        let result = sqlx::query(
            r#"
            INSERT INTO joysafeter_session_events (id, session_id, event_type, payload, seq, created_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (id) DO NOTHING
            "#,
        )
        .bind(id)
        .bind(session_id)
        .bind(event_type)
        .bind(payload)
        .bind(seq)
        .execute(pool)
        .await?;
        total += result.rows_affected();
    }
    Ok(total)
}
