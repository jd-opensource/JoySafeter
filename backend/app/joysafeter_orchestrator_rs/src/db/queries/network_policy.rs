//! Typed persistence boundary for sandbox network-policy generations.

use serde_json::Value;
use sqlx::PgPool;

use crate::ids::{SandboxId, SandboxNetworkPolicyId, SessionId, TaskId};
use crate::kernel::network_policy::NetworkPolicyGeneration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkPolicyStatus {
    Disabled,
    Pending,
    Ready,
    Nacked,
    Failed,
}

impl NetworkPolicyStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::Pending => "pending",
            Self::Ready => "ready",
            Self::Nacked => "nacked",
            Self::Failed => "failed",
        }
    }
}

#[derive(Debug, Clone)]
pub struct UpsertNetworkPolicy<'a> {
    pub id: SandboxNetworkPolicyId,
    pub sandbox_id: SandboxId,
    pub session_id: Option<SessionId>,
    pub task_id: Option<TaskId>,
    pub generation: &'a NetworkPolicyGeneration,
    pub desired_policy_json: &'a Value,
    pub rendered_summary_json: &'a Value,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NetworkPolicyPrepareOutcome {
    Pending(NetworkPolicyGeneration),
    AlreadyReady(NetworkPolicyGeneration),
}

impl NetworkPolicyPrepareOutcome {
    pub fn generation(&self) -> &NetworkPolicyGeneration {
        match self {
            Self::Pending(generation) | Self::AlreadyReady(generation) => generation,
        }
    }

    pub fn into_generation(self) -> NetworkPolicyGeneration {
        match self {
            Self::Pending(generation) | Self::AlreadyReady(generation) => generation,
        }
    }

    pub fn is_already_ready(&self) -> bool {
        matches!(self, Self::AlreadyReady(_))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkPolicyAckOutcome {
    Applied,
    AlreadyReady,
    Stale,
    Missing,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkPolicyFailureOutcome {
    Recorded,
    AlreadyReady,
    Stale,
    Missing,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RecoveryGenerationPrepareOutcome {
    Pending(NetworkPolicyGeneration),
    Stale,
    Missing,
}

#[derive(Debug, sqlx::FromRow)]
struct NetworkPolicyState {
    networking_status: String,
    networking_policy_hash: Option<String>,
    networking_policy_version: i64,
    networking_applied_hash: Option<String>,
    networking_applied_version: Option<i64>,
}

impl NetworkPolicyState {
    fn desired_matches(&self, generation: &NetworkPolicyGeneration) -> bool {
        self.networking_policy_hash.as_deref() == Some(&generation.policy_hash)
            && self.networking_policy_version == generation.policy_version
    }

    fn is_ready_for(&self, generation: &NetworkPolicyGeneration) -> bool {
        self.networking_status == "ready"
            && self.desired_matches(generation)
            && self.networking_applied_hash.as_deref() == Some(&generation.policy_hash)
            && self.networking_applied_version == Some(generation.policy_version)
    }
}

/// Persist a fail-closed recovery quarantine only if the observed durable
/// generation is still current. Recovery must never overwrite a newer policy.
pub async fn quarantine_recovery_generation(
    pool: &PgPool,
    sandbox_id: SandboxId,
    observed_policy_hash: Option<&str>,
    observed_policy_version: i64,
    reason: &str,
) -> Result<NetworkPolicyFailureOutcome, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = $2,
            networking_last_error = $3,
            networking_applied_hash = NULL,
            networking_applied_version = NULL,
            networking_ready_at = NULL,
            updated_at = NOW()
        WHERE id = $1
          AND destroyed_at IS NULL
          AND networking_policy_hash IS NOT DISTINCT FROM $4
          AND networking_policy_version = $5
        "#,
    )
    .bind(sandbox_id)
    .bind(NetworkPolicyStatus::Failed.as_str())
    .bind(reason)
    .bind(observed_policy_hash)
    .bind(observed_policy_version)
    .execute(pool)
    .await?;

    if result.rows_affected() > 0 {
        return Ok(NetworkPolicyFailureOutcome::Recorded);
    }
    Ok(match load_network_policy_state(pool, sandbox_id).await? {
        None => NetworkPolicyFailureOutcome::Missing,
        Some(_) => NetworkPolicyFailureOutcome::Stale,
    })
}

/// Prepare the desired generation without reopening an already-ready policy.
pub async fn prepare_generation(
    pool: &PgPool,
    sandbox_id: SandboxId,
    policy_hash: &str,
) -> Result<NetworkPolicyPrepareOutcome, sqlx::Error> {
    let mut transaction = pool.begin().await?;
    let current = sqlx::query_as::<_, NetworkPolicyState>(
        r#"
        SELECT networking_status, networking_policy_hash, networking_policy_version,
               networking_applied_hash, networking_applied_version
        FROM joysafeter_sandboxes
        WHERE id = $1 AND destroyed_at IS NULL
        FOR UPDATE
        "#,
    )
    .bind(sandbox_id)
    .fetch_optional(&mut *transaction)
    .await?
    .ok_or(sqlx::Error::RowNotFound)?;
    let generation = NetworkPolicyGeneration {
        policy_hash: policy_hash.to_string(),
        policy_version: if current.networking_policy_hash.as_deref() == Some(policy_hash) {
            current.networking_policy_version
        } else {
            current.networking_policy_version.max(0) + 1
        },
    };
    if current.is_ready_for(&generation) {
        transaction.commit().await?;
        return Ok(NetworkPolicyPrepareOutcome::AlreadyReady(generation));
    }
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = 'pending',
            networking_policy_hash = $2,
            networking_policy_version = $3,
            networking_last_error = NULL,
            updated_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .bind(policy_hash)
    .bind(generation.policy_version)
    .execute(&mut *transaction)
    .await?;
    transaction.commit().await?;
    Ok(NetworkPolicyPrepareOutcome::Pending(generation))
}

pub async fn retry_generation(
    pool: &PgPool,
    sandbox_id: SandboxId,
    policy_hash: &str,
) -> Result<NetworkPolicyGeneration, sqlx::Error> {
    let row = sqlx::query_as::<_, (String, i64)>(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = 'pending', networking_last_error = NULL, updated_at = NOW()
        WHERE id = $1 AND destroyed_at IS NULL AND networking_policy_hash = $2
        RETURNING networking_policy_hash, networking_policy_version
        "#,
    )
    .bind(sandbox_id)
    .bind(policy_hash)
    .fetch_one(pool)
    .await?;
    Ok(NetworkPolicyGeneration {
        policy_hash: row.0,
        policy_version: row.1,
    })
}

/// Reopen or advance a recovery generation only while the row still matches
/// the snapshot used to render it. This prevents staging from publishing a
/// policy derived from stale sandbox or credential state.
pub async fn prepare_recovery_generation(
    pool: &PgPool,
    sandbox_id: SandboxId,
    observed_policy_hash: Option<&str>,
    observed_policy_version: i64,
    canonical_policy_hash: &str,
) -> Result<RecoveryGenerationPrepareOutcome, sqlx::Error> {
    let mut transaction = pool.begin().await?;
    let current = sqlx::query_as::<_, NetworkPolicyState>(
        r#"
        SELECT networking_status, networking_policy_hash, networking_policy_version,
               networking_applied_hash, networking_applied_version
        FROM joysafeter_sandboxes
        WHERE id = $1 AND destroyed_at IS NULL
        FOR UPDATE
        "#,
    )
    .bind(sandbox_id)
    .fetch_optional(&mut *transaction)
    .await?;
    let Some(current) = current else {
        transaction.commit().await?;
        return Ok(RecoveryGenerationPrepareOutcome::Missing);
    };
    if current.networking_policy_hash.as_deref() != observed_policy_hash
        || current.networking_policy_version != observed_policy_version
    {
        transaction.commit().await?;
        return Ok(RecoveryGenerationPrepareOutcome::Stale);
    }

    let generation = NetworkPolicyGeneration {
        policy_hash: canonical_policy_hash.to_string(),
        policy_version: if observed_policy_hash == Some(canonical_policy_hash) {
            observed_policy_version
        } else {
            observed_policy_version.max(0) + 1
        },
    };
    sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = 'pending',
            networking_policy_hash = $2,
            networking_policy_version = $3,
            networking_applied_hash = NULL,
            networking_applied_version = NULL,
            networking_last_error = NULL,
            networking_ready_at = NULL,
            updated_at = NOW()
        WHERE id = $1
        "#,
    )
    .bind(sandbox_id)
    .bind(&generation.policy_hash)
    .bind(generation.policy_version)
    .execute(&mut *transaction)
    .await?;
    transaction.commit().await?;
    Ok(RecoveryGenerationPrepareOutcome::Pending(generation))
}

/// Mark only the exact accepted network-policy generation as ready.
pub async fn mark_generation_applied(
    pool: &PgPool,
    sandbox_id: SandboxId,
    generation: &NetworkPolicyGeneration,
) -> Result<NetworkPolicyAckOutcome, sqlx::Error> {
    let result = sqlx::query(
        r#"
        UPDATE joysafeter_sandboxes
        SET networking_status = 'ready',
            networking_applied_hash = $2,
            networking_applied_version = $3,
            networking_last_error = NULL,
            networking_ready_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
          AND destroyed_at IS NULL
          AND networking_status = 'pending'
          AND networking_policy_hash = $2
          AND networking_policy_version = $3
        "#,
    )
    .bind(sandbox_id)
    .bind(&generation.policy_hash)
    .bind(generation.policy_version)
    .execute(pool)
    .await?;

    if result.rows_affected() > 0 {
        return Ok(NetworkPolicyAckOutcome::Applied);
    }
    Ok(match load_network_policy_state(pool, sandbox_id).await? {
        None => NetworkPolicyAckOutcome::Missing,
        Some(state) if state.is_ready_for(generation) => NetworkPolicyAckOutcome::AlreadyReady,
        Some(_) => NetworkPolicyAckOutcome::Stale,
    })
}

/// Persist a failed policy application with the redacted desired/rendered policy.
pub async fn record_generation_failure(
    pool: &PgPool,
    policy: UpsertNetworkPolicy<'_>,
    reason: &str,
) -> Result<NetworkPolicyFailureOutcome, sqlx::Error> {
    let result = sqlx::query(
        r#"
        WITH status_update AS (
            UPDATE joysafeter_sandboxes
            SET networking_status = 'nacked',
                networking_last_error = $7,
                updated_at = NOW()
            WHERE id = $1
              AND destroyed_at IS NULL
              AND networking_status = 'pending'
              AND networking_policy_hash = $2
              AND networking_policy_version = $3
            RETURNING id,
                      chat_session_id,
                      networking_policy_version AS policy_version
        )
        INSERT INTO joysafeter_sandbox_network_policies (
            id, sandbox_id, session_id, task_id, policy_hash, policy_version,
            desired_policy_json, rendered_summary_json, status,
            last_error, last_nack_reason, created_at, updated_at
        )
        SELECT $9,
               status_update.id,
               COALESCE($4, status_update.chat_session_id),
               $5,
               $2,
               status_update.policy_version,
               $6,
               $8,
               'nacked',
               $7,
               $7,
               NOW(),
               NOW()
        FROM status_update
        ON CONFLICT (sandbox_id, policy_version) DO UPDATE
        SET session_id = COALESCE(EXCLUDED.session_id, joysafeter_sandbox_network_policies.session_id),
            task_id = COALESCE(EXCLUDED.task_id, joysafeter_sandbox_network_policies.task_id),
            policy_hash = EXCLUDED.policy_hash,
            desired_policy_json = EXCLUDED.desired_policy_json,
            rendered_summary_json = EXCLUDED.rendered_summary_json,
            status = 'nacked',
            last_error = EXCLUDED.last_error,
            last_nack_reason = EXCLUDED.last_nack_reason,
            updated_at = NOW()
        "#,
    )
    .bind(policy.sandbox_id)
    .bind(&policy.generation.policy_hash)
    .bind(policy.generation.policy_version)
    .bind(policy.session_id)
    .bind(policy.task_id)
    .bind(policy.desired_policy_json)
    .bind(reason)
    .bind(policy.rendered_summary_json)
    .bind(policy.id)
    .execute(pool)
    .await?;

    if result.rows_affected() > 0 {
        return Ok(NetworkPolicyFailureOutcome::Recorded);
    }
    Ok(
        match load_network_policy_state(pool, policy.sandbox_id).await? {
            None => NetworkPolicyFailureOutcome::Missing,
            Some(state) if state.is_ready_for(policy.generation) => {
                NetworkPolicyFailureOutcome::AlreadyReady
            }
            Some(_) => NetworkPolicyFailureOutcome::Stale,
        },
    )
}

async fn load_network_policy_state(
    pool: &PgPool,
    sandbox_id: SandboxId,
) -> Result<Option<NetworkPolicyState>, sqlx::Error> {
    sqlx::query_as::<_, NetworkPolicyState>(
        r#"
        SELECT networking_status, networking_policy_hash, networking_policy_version,
               networking_applied_hash, networking_applied_version
        FROM joysafeter_sandboxes
        WHERE id = $1 AND destroyed_at IS NULL
        "#,
    )
    .bind(sandbox_id)
    .fetch_optional(pool)
    .await
}
