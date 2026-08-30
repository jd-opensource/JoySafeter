use sqlx::PgPool;

use crate::ids::{SessionId, TaskId};

const EVENT_LIMIT: i64 = 100;
const MAX_CHARS: usize = 24_000;

pub(super) async fn load(pool: &PgPool, session_id: SessionId, task_id: TaskId) -> String {
    let current_turn_running_seq: Option<i64> = sqlx::query_scalar(
        r#"
        SELECT MAX(seq) FROM joysafeter_session_events
        WHERE session_id = $1
          AND event_type = 'session.status_running'
          AND payload->>'task_id' = $2
        "#,
    )
    .bind(session_id)
    .bind(task_id.to_string())
    .fetch_optional(pool)
    .await
    .ok()
    .flatten()
    .flatten();

    let boundary_seq: Option<i64> = if let Some(running_seq) = current_turn_running_seq {
        let user_message_seq: Option<i64> = sqlx::query_scalar(
            r#"
            SELECT MAX(seq) FROM joysafeter_session_events
            WHERE session_id = $1
              AND event_type = 'user.message'
              AND seq < $2
            "#,
        )
        .bind(session_id)
        .bind(running_seq)
        .fetch_optional(pool)
        .await
        .ok()
        .flatten()
        .flatten();
        user_message_seq.or(current_turn_running_seq)
    } else {
        None
    };

    let rows: Vec<(String, Option<serde_json::Value>)> = match sqlx::query_as(
        r#"
        SELECT event_type, payload FROM (
            SELECT event_type, payload, seq, created_at
            FROM joysafeter_session_events
            WHERE session_id = $1 AND ($2::bigint IS NULL OR seq < $2)
            ORDER BY seq DESC, created_at DESC
            LIMIT $3
        ) recent
        ORDER BY seq ASC, created_at ASC
        "#,
    )
    .bind(session_id)
    .bind(boundary_seq)
    .bind(EVENT_LIMIT)
    .fetch_all(pool)
    .await
    {
        Ok(rows) => rows,
        Err(_) => return String::new(),
    };

    let lines = rows
        .into_iter()
        .filter_map(|(event_type, payload)| {
            let text = extract_content_text(&payload?);
            if text.is_empty() {
                return None;
            }
            match event_type.as_str() {
                "user.message" => Some(format!("User: {text}")),
                "agent.message" => Some(format!("Assistant: {text}")),
                _ => None,
            }
        })
        .collect();
    let body = trim_history_lines_to_budget(lines, MAX_CHARS);
    if body.is_empty() {
        return String::new();
    }

    format!(
        "[CONVERSATION HISTORY - Prior turns in this session]\n{body}\n[END CONVERSATION HISTORY]"
    )
}

fn trim_history_lines_to_budget(lines: Vec<String>, max_chars: usize) -> String {
    if lines.is_empty() || max_chars == 0 {
        return String::new();
    }

    let mut selected = Vec::new();
    let mut used = 0usize;
    for line in lines.into_iter().rev() {
        let line_chars = line.chars().count();
        let separator_chars = if selected.is_empty() { 0 } else { 2 };
        if used + separator_chars + line_chars <= max_chars {
            used += separator_chars + line_chars;
            selected.push(line);
            continue;
        }

        if selected.is_empty() {
            let remaining = max_chars.saturating_sub(separator_chars);
            let truncated = truncate_start_chars(&line, remaining);
            if !truncated.is_empty() {
                selected.push(truncated);
            }
        }
        break;
    }

    selected.reverse();
    selected.join("\n\n")
}

fn truncate_start_chars(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_string();
    }
    if max_chars == 0 {
        return String::new();
    }
    const PREFIX: &str = "...";
    if max_chars <= PREFIX.len() {
        return value
            .chars()
            .rev()
            .take(max_chars)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect();
    }

    let keep_chars = max_chars - PREFIX.len();
    let suffix: String = value
        .chars()
        .rev()
        .take(keep_chars)
        .collect::<Vec<_>>()
        .into_iter()
        .rev()
        .collect();
    format!("{PREFIX}{suffix}")
}

fn extract_content_text(payload: &serde_json::Value) -> String {
    let Some(content) = payload.get("content") else {
        return String::new();
    };
    if let Some(text) = content.as_str() {
        return text.trim().to_string();
    }
    let Some(blocks) = content.as_array() else {
        return String::new();
    };
    blocks
        .iter()
        .filter(|block| block.get("type").and_then(|value| value.as_str()) == Some("text"))
        .filter_map(|block| block.get("text").and_then(|value| value.as_str()))
        .collect::<String>()
        .trim()
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::{extract_content_text, trim_history_lines_to_budget};

    #[test]
    fn trims_history_to_newest_lines_under_budget() {
        let body = trim_history_lines_to_budget(
            vec![
                "User: older".to_string(),
                "Assistant: middle".to_string(),
                "User: newest".to_string(),
            ],
            31,
        );

        assert_eq!(body, "Assistant: middle\n\nUser: newest");
    }

    #[test]
    fn extracts_plain_string_content() {
        let payload = serde_json::json!({ "content": " hello " });

        assert_eq!(extract_content_text(&payload), "hello");
    }

    #[test]
    fn extracts_text_block_content() {
        let payload = serde_json::json!({
            "content": [
                { "type": "text", "text": "hello" },
                { "type": "image", "url": "ignored" },
                { "type": "text", "text": " world" }
            ]
        });

        assert_eq!(extract_content_text(&payload), "hello world");
    }
}
