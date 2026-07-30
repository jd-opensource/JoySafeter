use std::time::Duration;

use anyhow::Context;
use chrono::{DateTime, Utc};
use serde_json::{json, Value};
use sqlx::PgPool;
use tracing::{info, warn};
use uuid::Uuid;

const EVEROS_DEFAULT_BASE_URL: &str = "http://everos:8003";
const EVEROS_APP_ID: &str = "joysafeter";
const EVEROS_PROJECT_ID_SEPARATOR: &str = "__";
const EVEROS_PROJECT_ID_MAX_LENGTH: usize = 128;

#[derive(Debug, Clone)]
pub struct SessionEventForMemory {
    pub event_type: String,
    pub payload: Value,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, sqlx::FromRow)]
struct TaskMemoryContext {
    prompt: String,
    created_at: DateTime<Utc>,
    task_project_id: Option<String>,
    task_agent_id: Option<Uuid>,
    task_user_id: Option<String>,
    session_id: Option<Uuid>,
    session_project_id: Option<String>,
    session_agent_id: Option<Uuid>,
    project_slug: Option<String>,
    user_name: Option<String>,
}

#[derive(Debug, Clone, sqlx::FromRow)]
struct SessionEventRow {
    event_type: String,
    payload: Value,
    created_at: DateTime<Utc>,
}

pub async fn sync_task_to_everos_agent_memory(pool: &PgPool, task_id: Uuid) -> anyhow::Result<()> {
    let Some(ctx) = load_task_memory_context(pool, task_id).await? else {
        warn!(task_id = %task_id, "Skipping EverOS add because task was not found");
        return Ok(());
    };
    let Some(session_id) = ctx.session_id else {
        warn!(task_id = %task_id, "Skipping EverOS add because task has no session_id");
        return Ok(());
    };
    let Some(agent_id) = ctx.task_agent_id.or(ctx.session_agent_id) else {
        warn!(task_id = %task_id, session_id = %session_id, "Skipping EverOS add because task/session has no agent_id");
        return Ok(());
    };

    let project_id = ctx
        .task_project_id
        .as_deref()
        .or(ctx.session_project_id.as_deref())
        .unwrap_or("default");
    let everos_project_id = compose_everos_project_id(ctx.project_slug.as_deref(), project_id);
    let everos_session_id = everos_path_safe_id(&session_id.to_string(), "default_session");
    let everos_user_id =
        compose_everos_user_id(ctx.user_name.as_deref(), ctx.task_user_id.as_deref());

    let events = list_task_memory_events(pool, session_id, task_id).await?;
    let messages = build_agent_memory_messages(
        &ctx.prompt,
        ctx.created_at,
        &events,
        &everos_user_id,
        agent_id,
    );
    if messages.is_empty() {
        info!(task_id = %task_id, session_id = %session_id, "Skipping EverOS add because this turn produced no memory messages");
        return Ok(());
    }

    let payload = json!({
        "app_id": EVEROS_APP_ID,
        "project_id": everos_project_id,
        "session_id": everos_session_id,
        "messages": messages,
    });
    post_to_everos(payload).await?;
    info!(task_id = %task_id, session_id = %session_id, "Submitted completed turn to EverOS /memory/add");
    Ok(())
}

async fn load_task_memory_context(
    pool: &PgPool,
    task_id: Uuid,
) -> Result<Option<TaskMemoryContext>, sqlx::Error> {
    sqlx::query_as::<_, TaskMemoryContext>(
        r#"
        SELECT
            t.prompt,
            t.created_at,
            t.project_id AS task_project_id,
            t.agent_id AS task_agent_id,
            t.user_id AS task_user_id,
            t.chat_session_id AS session_id,
            s.project_id AS session_project_id,
            s.agent_id AS session_agent_id,
            p.slug AS project_slug,
            u.name AS user_name
        FROM joysafeter_tasks t
        LEFT JOIN joysafeter_sessions s ON s.id = t.chat_session_id
        LEFT JOIN joysafeter_organization_projects p
          ON p.id = COALESCE(t.project_id, s.project_id)
        LEFT JOIN joysafeter_users u ON u.id = t.user_id
        WHERE t.id = $1
        "#,
    )
    .bind(task_id)
    .fetch_optional(pool)
    .await
}

async fn list_task_memory_events(
    pool: &PgPool,
    session_id: Uuid,
    task_id: Uuid,
) -> Result<Vec<SessionEventForMemory>, sqlx::Error> {
    let rows = sqlx::query_as::<_, SessionEventRow>(
        r#"
        SELECT event_type, payload, created_at
        FROM joysafeter_session_events
        WHERE session_id = $1
          AND seq > (
              SELECT COALESCE(MAX(seq), 0)
              FROM joysafeter_session_events
              WHERE session_id = $1
                AND event_type = 'session.status_running'
                AND payload->>'task_id' = $2
          )
          AND event_type IN (
              'agent.message',
              'agent.tool_use',
              'agent.tool_result',
              'agent.mcp_tool_use',
              'agent.mcp_tool_result'
          )
        ORDER BY seq ASC, created_at ASC
        "#,
    )
    .bind(session_id)
    .bind(task_id.to_string())
    .fetch_all(pool)
    .await?;

    Ok(rows
        .into_iter()
        .map(|row| SessionEventForMemory {
            event_type: row.event_type,
            payload: row.payload,
            created_at: row.created_at,
        })
        .collect())
}

pub fn build_agent_memory_messages(
    task_prompt: &str,
    task_created_at: DateTime<Utc>,
    session_events: &[SessionEventForMemory],
    user_id: &str,
    agent_id: Uuid,
) -> Vec<Value> {
    let agent_sender_id = everos_path_safe_id(&agent_id.to_string(), "default_agent");
    let user_sender_id = everos_path_safe_id(user_id, "default_user");
    let mut messages = Vec::new();

    if !task_prompt.trim().is_empty() {
        messages.push(json!({
            "role": "user",
            "sender_id": user_sender_id,
            "timestamp": task_created_at.timestamp_millis(),
            "content": task_prompt,
        }));
    }

    for event in session_events {
        match event.event_type.as_str() {
            "agent.message" => {
                let content = extract_text_content(&event.payload);
                if !content.trim().is_empty() {
                    messages.push(json!({
                        "role": "assistant",
                        "sender_id": agent_sender_id,
                        "timestamp": event.created_at.timestamp_millis(),
                        "content": content,
                    }));
                }
            }
            "agent.tool_use" | "agent.mcp_tool_use" => {
                let name = event
                    .payload
                    .get("name")
                    .and_then(Value::as_str)
                    .unwrap_or("tool");
                let call_id = event
                    .payload
                    .get("_call_id")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if call_id.is_empty() {
                    continue;
                }
                let arguments = event
                    .payload
                    .get("input")
                    .map(compact_json_string)
                    .unwrap_or_else(|| "{}".to_string());
                messages.push(json!({
                    "role": "assistant",
                    "sender_id": agent_sender_id,
                    "timestamp": event.created_at.timestamp_millis(),
                    "content": "",
                    "tool_calls": [{
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": arguments,
                        },
                    }],
                }));
            }
            "agent.tool_result" | "agent.mcp_tool_result" => {
                let tool_call_id = event
                    .payload
                    .get("tool_use_id")
                    .and_then(Value::as_str)
                    .unwrap_or("");
                if tool_call_id.is_empty() {
                    continue;
                }
                messages.push(json!({
                    "role": "tool",
                    "sender_id": agent_sender_id,
                    "timestamp": event.created_at.timestamp_millis(),
                    "tool_call_id": tool_call_id,
                    "content": extract_text_content(&event.payload),
                }));
            }
            _ => {}
        }
    }

    messages
}

async fn post_to_everos(payload: Value) -> anyhow::Result<()> {
    let url = everos_memory_add_url();
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
        .context("failed to build EverOS HTTP client")?;
    let response = client
        .post(&url)
        .json(&payload)
        .send()
        .await
        .with_context(|| format!("failed to POST EverOS memory add to {url}"))?;
    let status = response.status();
    if !status.is_success() {
        let body = response.text().await.unwrap_or_default();
        anyhow::bail!("EverOS memory add returned {status}: {body}");
    }
    Ok(())
}

fn everos_memory_add_url() -> String {
    let base = std::env::var("EVEROS_INTERNAL_BASE_URL")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(|| {
            std::env::var("EVEROS_BASE_URL")
                .ok()
                .filter(|value| !value.trim().is_empty())
        })
        .unwrap_or_else(|| EVEROS_DEFAULT_BASE_URL.to_string());
    let base = base.trim().trim_end_matches('/');
    if base.ends_with("/api/v1/memory") {
        format!("{base}/add")
    } else {
        format!("{base}/api/v1/memory/add")
    }
}

fn compose_everos_project_id(project_slug: Option<&str>, project_id: &str) -> String {
    let stable_id = everos_path_safe_id(project_id, "default");
    let separator_len = EVEROS_PROJECT_ID_SEPARATOR.len();
    if stable_id.len() + separator_len >= EVEROS_PROJECT_ID_MAX_LENGTH {
        return stable_id
            .chars()
            .take(EVEROS_PROJECT_ID_MAX_LENGTH)
            .collect();
    }
    let max_slug_len = EVEROS_PROJECT_ID_MAX_LENGTH - separator_len - stable_id.len();
    let mut slug = everos_path_safe_id(project_slug.unwrap_or("project"), "project");
    slug = slug.chars().take(max_slug_len).collect();
    slug = slug.trim_matches(&['.', '_'][..]).to_string();
    if slug.is_empty() {
        slug = "project".to_string();
    }
    format!("{slug}{EVEROS_PROJECT_ID_SEPARATOR}{stable_id}")
}

fn compose_everos_user_id(user_name: Option<&str>, user_id: Option<&str>) -> String {
    everos_path_safe_id(
        user_name.or(user_id).unwrap_or("default_user"),
        "default_user",
    )
}

fn everos_path_safe_id(value: &str, fallback: &str) -> String {
    let mut safe = String::with_capacity(value.len());
    let mut last_was_underscore = false;
    for ch in value.trim().chars() {
        let allowed = ch.is_ascii_alphanumeric() || matches!(ch, '_' | '.' | '@' | '+' | '-');
        let next = if allowed { ch } else { '_' };
        if next == '_' {
            if !last_was_underscore {
                safe.push(next);
            }
            last_was_underscore = true;
        } else {
            safe.push(next);
            last_was_underscore = false;
        }
    }
    let safe = safe.trim_matches(&['.', '_'][..]);
    if safe.is_empty() || safe == "." || safe == ".." {
        fallback.to_string()
    } else {
        safe.chars().take(EVEROS_PROJECT_ID_MAX_LENGTH).collect()
    }
}

fn extract_text_content(payload: &Value) -> String {
    let Some(content) = payload.get("content") else {
        return String::new();
    };
    match content {
        Value::String(text) => text.clone(),
        Value::Array(items) => items
            .iter()
            .filter_map(|item| {
                if let Some(text) = item.get("text").and_then(Value::as_str) {
                    Some(text.to_string())
                } else {
                    item.as_str().map(ToString::to_string)
                }
            })
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    }
}

fn compact_json_string(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        _ => serde_json::to_string(value).unwrap_or_else(|_| "{}".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;
    use uuid::Uuid;

    #[test]
    fn build_agent_memory_messages_includes_one_user_turn_and_agent_trace() {
        let task_created_at = chrono::DateTime::parse_from_rfc3339("2026-07-30T10:00:00Z")
            .unwrap()
            .with_timezone(&chrono::Utc);
        let event_ts = chrono::DateTime::parse_from_rfc3339("2026-07-30T10:00:01Z")
            .unwrap()
            .with_timezone(&chrono::Utc);
        let events = vec![
            super::SessionEventForMemory {
                event_type: "agent.tool_use".to_string(),
                payload: json!({
                    "name": "Bash",
                    "_call_id": "toolu_1",
                    "input": {"command": "pwd"}
                }),
                created_at: event_ts,
            },
            super::SessionEventForMemory {
                event_type: "agent.tool_result".to_string(),
                payload: json!({
                    "tool_use_id": "toolu_1",
                    "content": [{"type": "text", "text": "/workspace"}]
                }),
                created_at: event_ts,
            },
            super::SessionEventForMemory {
                event_type: "agent.message".to_string(),
                payload: json!({
                    "content": [{"type": "text", "text": "done"}]
                }),
                created_at: event_ts,
            },
        ];

        let messages = super::build_agent_memory_messages(
            "run pwd",
            task_created_at,
            &events,
            "user-1",
            Uuid::parse_str("11111111-1111-1111-1111-111111111111").unwrap(),
        );

        assert_eq!(messages.len(), 4);
        assert_eq!(messages[0]["role"], "user");
        assert_eq!(messages[0]["sender_id"], "user-1");
        assert_eq!(messages[0]["content"], "run pwd");
        assert_eq!(messages[1]["role"], "assistant");
        assert_eq!(messages[1]["tool_calls"][0]["function"]["name"], "Bash");
        assert_eq!(
            messages[1]["tool_calls"][0]["function"]["arguments"],
            "{\"command\":\"pwd\"}"
        );
        assert_eq!(messages[2]["role"], "tool");
        assert_eq!(messages[2]["tool_call_id"], "toolu_1");
        assert_eq!(messages[2]["content"], "/workspace");
        assert_eq!(messages[3]["role"], "assistant");
        assert_eq!(messages[3]["content"], "done");
    }
}
