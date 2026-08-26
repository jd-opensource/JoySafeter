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

use crate::ids::{EnvironmentId, ProjectId, SessionId};
use crate::kernel::runtime_freshness::RuntimeFreshnessError;

/// A live environment row loaded under the strict binding rules.
#[derive(Debug, Clone, sqlx::FromRow)]
pub struct EnvironmentBinding {
    pub config: Value,
    pub image_tag: Option<String>,
    pub archived_at: Option<chrono::DateTime<chrono::Utc>>,
}

/// Resolve the authoritative environment ID for a run.
///
/// A persisted session owns its environment binding, including an explicit
/// absence of a binding. The live agent is consulted only before a session
/// exists.
pub fn environment_binding_ids(
    session_environment_id: Option<EnvironmentId>,
    agent_environment_id: Option<EnvironmentId>,
    session_id: Option<SessionId>,
) -> (bool, Option<EnvironmentId>) {
    if session_id.is_some() {
        (session_environment_id.is_some(), session_environment_id)
    } else {
        (false, agent_environment_id)
    }
}

/// Load a live environment by typed ID under the strict rules: not
/// deleted and never cross-project (`IS NOT DISTINCT FROM` so a NULL-project
/// row only matches a NULL project scope). `archived_at` is returned rather
/// than filtered in SQL so callers can distinguish archived from missing.
pub async fn load_environment_strict(
    pool: &PgPool,
    environment_id: EnvironmentId,
    project_id: Option<ProjectId>,
) -> Result<Option<EnvironmentBinding>, sqlx::Error> {
    sqlx::query_as::<_, EnvironmentBinding>(
        r#"
        SELECT config, image_tag, archived_at FROM joysafeter_environments
        WHERE id = $1 AND deleted_at IS NULL
          AND project_id IS NOT DISTINCT FROM $2
        "#,
    )
    .bind(environment_id)
    .bind(project_id)
    .fetch_optional(pool)
    .await
}

/// Resolve and validate the live environment binding for a run.
///
/// * `Ok(Some(_))` — the effective ID resolved to a non-archived,
///   same-project environment.
/// * `Ok(None)` — there is no binding, or an unbound agent environment is no
///   longer live before session creation.
/// * `Err(SessionBindingInvalid)` — an explicit session binding is missing,
///   archived, or cross-project. The run must not proceed against it, and the
///   resolver must not provision a sandbox the harness would reject.
pub async fn resolve_live_environment_binding(
    pool: &PgPool,
    session_environment_id: Option<EnvironmentId>,
    agent_environment_id: Option<EnvironmentId>,
    project_id: Option<ProjectId>,
    session_id: Option<SessionId>,
) -> Result<Option<EnvironmentBinding>, RuntimeFreshnessError> {
    let (explicit, effective) =
        environment_binding_ids(session_environment_id, agent_environment_id, session_id);
    let Some(environment_id) = effective else {
        return Ok(None);
    };
    let environment = load_environment_strict(pool, environment_id, project_id).await?;
    match environment.filter(|environment| environment.archived_at.is_none()) {
        Some(environment) => Ok(Some(environment)),
        None => {
            if explicit {
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
    use super::environment_binding_ids;
    use crate::ids::{EnvironmentId, SessionId};

    #[test]
    fn session_environment_id_is_authoritative() {
        let session_id = SessionId::new();
        let session_environment_id = EnvironmentId::new();
        let agent_environment_id = EnvironmentId::new();
        let (explicit, effective) = environment_binding_ids(
            Some(session_environment_id),
            Some(agent_environment_id),
            Some(session_id),
        );
        assert!(explicit);
        assert_eq!(effective, Some(session_environment_id));
    }

    #[test]
    fn session_without_environment_does_not_fall_back_to_agent() {
        let (explicit, effective) =
            environment_binding_ids(None, Some(EnvironmentId::new()), Some(SessionId::new()));
        assert!(!explicit);
        assert_eq!(effective, None);
    }

    #[test]
    fn agent_environment_id_is_used_before_session_creation() {
        let agent_environment_id = EnvironmentId::new();
        let (explicit, effective) = environment_binding_ids(None, Some(agent_environment_id), None);
        assert!(!explicit);
        assert_eq!(effective, Some(agent_environment_id));
    }

    #[test]
    fn no_ids_yield_none() {
        let (explicit, effective) = environment_binding_ids(None, None, None);
        assert!(!explicit);
        assert_eq!(effective, None);
    }
}
