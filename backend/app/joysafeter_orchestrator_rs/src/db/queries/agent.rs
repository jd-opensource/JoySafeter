use sqlx::PgPool;

use crate::db::models::JoySafeterAgent;
use crate::ids::AgentId;

// ---------------------------------------------------------------------------
// Agent queries
// ---------------------------------------------------------------------------

/// Get an agent by ID.
pub async fn get_agent(
    pool: &PgPool,
    agent_id: AgentId,
) -> Result<Option<JoySafeterAgent>, sqlx::Error> {
    sqlx::query_as::<_, JoySafeterAgent>(
        r#"
        SELECT id, project_id, name, engine_kind, model->>'id' AS model, system_prompt,
               description, env, mcp_servers, skills, agents, commands, tools,
               permission_mode, metadata, multiagent, version, environment_id, model_credential_id
        FROM joysafeter_agents
        WHERE id = $1 AND deleted_at IS NULL
        "#,
    )
    .bind(agent_id)
    .fetch_optional(pool)
    .await
}
