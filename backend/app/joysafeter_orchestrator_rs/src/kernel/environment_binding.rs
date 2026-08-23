//! Canonical live-environment binding resolution shared by the sandbox
//! resolver (pre-provision gate) and the harness input builder (`StartTask`
//! gate).
//!
//! Keeping a single implementation prevents the two stages from disagreeing
//! about which environment bindings are valid. A divergence let the resolver
//! provision a sandbox from an environment the harness then rejected, wasting
//! provisioning and surfacing a confusing terminal `SessionBindingInvalid`
//! after the sandbox already existed.

use serde_json::Value;
use sqlx::PgPool;

use crate::ids::{EnvironmentId, SessionId};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;

/// A live environment row loaded under the strict binding rules.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct EnvironmentBinding {
    pub config: Value,
    pub image_tag: Option<String>,
    pub archived_at: Option<chrono::DateTime<chrono::Utc>>,
}

/// Split the environment references that govern a run into the explicit
/// (session-bound, hard-fail) reference and the effective reference actually
/// used to load the environment.
///
/// Precedence: an explicit session binding wins and is a hard requirement; the
/// snapshot reference is preferred over the agent default for the soft
/// fallback.
pub fn environment_binding_refs(
    session_ref: Option<&str>,
    snapshot_ref: Option<&str>,
    agent_ref: Option<&str>,
) -> (Option<String>, Option<String>) {
    let normalize = |value: Option<&str>| {
        value
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(ToOwned::to_owned)
    };
    let explicit = normalize(session_ref);
    let fallback = normalize(snapshot_ref).or_else(|| normalize(agent_ref));
    let effective = explicit.clone().or(fallback);
    (explicit, effective)
}

/// Load a live environment by public id or name under the strict rules: not
/// deleted and never cross-project (`IS NOT DISTINCT FROM` so a NULL-project
/// row only matches a NULL project scope). `archived_at` is returned rather
/// than filtered in SQL so callers can distinguish archived from missing.
pub async fn load_environment_strict(
    pool: &PgPool,
    env_ref: &str,
    project_id: Option<&str>,
) -> Result<Option<EnvironmentBinding>, sqlx::Error> {
    if let Ok(env_id) = EnvironmentId::from_public(env_ref) {
        return sqlx::query_as::<_, EnvironmentBinding>(
            r#"
            SELECT config, image_tag, archived_at FROM joysafeter_environments
            WHERE id = $1 AND deleted_at IS NULL
              AND project_id IS NOT DISTINCT FROM $2
            "#,
        )
        .bind(env_id)
        .bind(project_id)
        .fetch_optional(pool)
        .await;
    }
    sqlx::query_as::<_, EnvironmentBinding>(
        r#"
        SELECT config, image_tag, archived_at FROM joysafeter_environments
        WHERE name = $1 AND deleted_at IS NULL
          AND project_id IS NOT DISTINCT FROM $2
        "#,
    )
    .bind(env_ref)
    .bind(project_id)
    .fetch_optional(pool)
    .await
}

/// Resolve and validate the live environment binding for a run.
///
/// * `Ok(Some(_))` — the effective reference resolved to a non-archived,
///   same-project environment.
/// * `Ok(None)` — there is no reference, or only a soft (snapshot/agent)
///   fallback reference that does not resolve.
/// * `Err(SessionBindingInvalid)` — an explicit session binding is missing,
///   archived, or cross-project. The run must not proceed against it, and the
///   resolver must not provision a sandbox the harness would reject.
pub async fn resolve_live_environment_binding(
    pool: &PgPool,
    session_ref: Option<&str>,
    snapshot_ref: Option<&str>,
    agent_ref: Option<&str>,
    project_id: Option<&str>,
    session_id: Option<SessionId>,
) -> Result<Option<EnvironmentBinding>, RuntimeFreshnessError> {
    let (explicit, effective) = environment_binding_refs(session_ref, snapshot_ref, agent_ref);
    let Some(env_ref) = effective else {
        return Ok(None);
    };
    let environment = load_environment_strict(pool, &env_ref, project_id).await?;
    match environment.filter(|environment| environment.archived_at.is_none()) {
        Some(environment) => Ok(Some(environment)),
        None => {
            if explicit.is_some() {
                Err(RuntimeFreshnessError::SessionBindingInvalid {
                    session_id: session_id
                        .expect("explicit environment binding requires a session"),
                    reason: "environment binding is missing, archived, or cross-project",
                })
            } else {
                Ok(None)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::environment_binding_refs;

    #[test]
    fn explicit_session_ref_is_hard_requirement_and_wins() {
        let (explicit, effective) =
            environment_binding_refs(Some("env_session"), Some("env_snapshot"), Some("env_agent"));
        assert_eq!(explicit.as_deref(), Some("env_session"));
        assert_eq!(effective.as_deref(), Some("env_session"));
    }

    #[test]
    fn snapshot_ref_preferred_over_agent_for_fallback() {
        let (explicit, effective) =
            environment_binding_refs(None, Some("env_snapshot"), Some("env_agent"));
        assert_eq!(explicit, None);
        assert_eq!(effective.as_deref(), Some("env_snapshot"));
    }

    #[test]
    fn agent_ref_is_last_resort_fallback() {
        let (explicit, effective) = environment_binding_refs(None, None, Some("env_agent"));
        assert_eq!(explicit, None);
        assert_eq!(effective.as_deref(), Some("env_agent"));
    }

    #[test]
    fn blank_refs_are_ignored() {
        let (explicit, effective) =
            environment_binding_refs(Some("  "), Some(""), Some("env_agent"));
        assert_eq!(explicit, None);
        assert_eq!(effective.as_deref(), Some("env_agent"));
    }

    #[test]
    fn no_refs_yield_none() {
        let (explicit, effective) = environment_binding_refs(None, None, None);
        assert_eq!(explicit, None);
        assert_eq!(effective, None);
    }
}
