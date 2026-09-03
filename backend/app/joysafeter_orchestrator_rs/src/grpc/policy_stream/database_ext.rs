use sqlx::PgPool;

use crate::proto::policy_stream::{DeliveryStatus, PolicyGeneration};

/// Update a sandbox's networking delivery status after the gateway reports the
/// outcome over the policy stream. Uses a runtime query (no compile-time schema
/// cache required).
pub async fn update_sandbox_delivery(
    pool: &PgPool,
    sandbox_id: &str,
    generation: Option<&PolicyGeneration>,
    status: i32,
    error_message: &str,
) -> anyhow::Result<()> {
    let status_enum = DeliveryStatus::try_from(status).unwrap_or(DeliveryStatus::Failed);

    let (networking_status, applied_version, last_error): (&str, Option<i64>, Option<&str>) =
        match status_enum {
            DeliveryStatus::Delivered => {
                let version = generation.map(|g| g.policy_version as i64);
                ("applied", version, None)
            }
            DeliveryStatus::Failed => (
                "failed",
                None,
                if error_message.is_empty() {
                    None
                } else {
                    Some(error_message)
                },
            ),
        };

    let sandbox_uuid = uuid::Uuid::parse_str(sandbox_id)
        .map_err(|_| anyhow::anyhow!("invalid sandbox id in delivery report: {sandbox_id}"))?;

    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = $1,
            networking_applied_version = COALESCE($2, networking_applied_version),
            networking_last_error = $3,
            updated_at = NOW()
        WHERE id = $4
        "#,
    )
    .bind(networking_status)
    .bind(applied_version)
    .bind(last_error)
    .bind(sandbox_uuid)
    .execute(pool)
    .await?;

    Ok(())
}
