use std::collections::HashSet;

use serde_json::{json, Value};

use crate::grpc::proto;

/// Map a RunnerHarnessEvent proto message to a (event_type, payload) pair.
///
/// Mirrors the Python `map_harness_event` from `event_mapping.py`.
/// Takes optional tool name sets for routing custom vs MCP tool events.
pub fn map_harness_event(
    event: &proto::RunnerHarnessEvent,
    custom_tool_names: Option<&HashSet<String>>,
    mcp_server_names: Option<&HashSet<String>>,
) -> Option<(String, Value)> {
    let inner = event.event.as_ref()?;

    match inner {
        // Python L124: content is a list of content blocks
        proto::runner_harness_event::Event::Text(e) => Some((
            "agent.message".to_string(),
            json!({ "content": [{"type": "text", "text": e.content}] }),
        )),
        // Python L127: empty dict, no content field
        proto::runner_harness_event::Event::Thinking(_e) => {
            Some(("agent.thinking".to_string(), json!({})))
        }
        proto::runner_harness_event::Event::ToolUse(e) => {
            let tool_name = &e.tool;
            let is_custom = custom_tool_names
                .map(|s| s.contains(tool_name))
                .unwrap_or(false);
            let is_mcp = mcp_server_names
                .map(|s| s.contains(tool_name))
                .unwrap_or(false);

            let event_type = if is_custom {
                "agent.custom_tool_use"
            } else if is_mcp {
                "agent.mcp_tool_use"
            } else {
                "agent.tool_use"
            };

            let mut payload = json!({
                "name": e.tool,
                "_call_id": e.call_id,
                // input_json arrives as a JSON-encoded string from the runner
                // (proto field `input_json: string`). Parse it back to a Value
                // so consumers see structured fields, not a doubly-escaped
                // string. Preserve the historical gRPC event contract:
                // consumers receive parsed input objects when JSON is valid.
                "input": serde_json::from_str::<Value>(&e.input_json)
                    .unwrap_or_else(|_| Value::String(e.input_json.clone())),
            });
            if e.is_control_request {
                if let Some(obj) = payload.as_object_mut() {
                    obj.insert("is_control_request".to_string(), Value::Bool(true));
                }
            }

            Some((event_type.to_string(), payload))
        }
        proto::runner_harness_event::Event::ToolResult(e) => {
            let tool_name = &e.tool;
            let is_custom = custom_tool_names
                .map(|s| s.contains(tool_name))
                .unwrap_or(false);
            // Suppress custom tool results (they are handled by the HITL flow)
            if is_custom {
                return None;
            }

            // Check if this is an MCP tool result (matching Python event_mapping.py line 153)
            let is_mcp = mcp_server_names
                .map(|s| s.contains(tool_name))
                .unwrap_or(false);

            let event_type = if is_mcp {
                "agent.mcp_tool_result"
            } else {
                "agent.tool_result"
            };

            Some((
                event_type.to_string(),
                json!({
                    "tool_use_id": e.call_id,
                    "content": [{"type": "text", "text": e.output}],
                    "is_error": false,
                }),
            ))
        }
        proto::runner_harness_event::Event::Error(e) => Some((
            "session.error".to_string(),
            json!({
                "error": {
                    "message": e.message,
                    "retry_status": { "type": "terminal" },
                },
            }),
        )),
        proto::runner_harness_event::Event::Status(_e) => None,
        proto::runner_harness_event::Event::Log(_e) => {
            // Suppress log events (matching Python behavior)
            None
        }
        proto::runner_harness_event::Event::ModelRequestStart(e) => Some((
            "span.model_request_start".to_string(),
            json!({ "model": e.model }),
        )),
        // Python L84-96: only model + usage (no flat token fields)
        proto::runner_harness_event::Event::ModelRequestEnd(e) => Some((
            "span.model_request_end".to_string(),
            json!({
                "model": e.model,
                "usage": {
                    "input_tokens": e.input_tokens,
                    "output_tokens": e.output_tokens,
                    "cache_read_input_tokens": e.cache_read_tokens,
                    "cache_creation_input_tokens": e.cache_write_tokens,
                },
            }),
        )),
        // Background sub-agent lifecycle (claude-code Task tool with
        // run_in_background=true). Phase: "started" | "progress" |
        // "completed" | "failed" | "stopped". Mirrors the Python mapper.
        proto::runner_harness_event::Event::TaskNotification(e) => {
            let event_type = match e.phase.as_str() {
                "started" => "agent.bg_task_started",
                "progress" => "agent.bg_task_progress",
                _ => "agent.bg_task_finished",
            };
            let mut payload = serde_json::Map::new();
            payload.insert("phase".into(), Value::String(e.phase.clone()));
            payload.insert(
                "subagent_task_id".into(),
                Value::String(e.subagent_task_id.clone()),
            );
            if let Some(v) = e.tool_use_id.as_ref() {
                payload.insert("tool_use_id".into(), Value::String(v.clone()));
            }
            if let Some(v) = e.description.as_ref() {
                payload.insert("description".into(), Value::String(v.clone()));
            }
            if let Some(v) = e.status.as_ref() {
                payload.insert("status".into(), Value::String(v.clone()));
            }
            if let Some(v) = e.summary.as_ref() {
                payload.insert("summary".into(), Value::String(v.clone()));
            }
            if let Some(v) = e.result.as_ref() {
                payload.insert("result".into(), Value::String(v.clone()));
            }
            if let Some(v) = e.output_file.as_ref() {
                payload.insert("output_file".into(), Value::String(v.clone()));
            }
            if let Some(v) = e.last_tool_name.as_ref() {
                payload.insert("last_tool_name".into(), Value::String(v.clone()));
            }
            if let Some(v) = e.total_tokens {
                payload.insert("total_tokens".into(), Value::Number(v.into()));
            }
            if let Some(v) = e.tool_uses {
                payload.insert("tool_uses".into(), Value::Number(v.into()));
            }
            if let Some(v) = e.duration_ms {
                payload.insert("duration_ms".into(), Value::Number(v.into()));
            }
            Some((event_type.to_string(), Value::Object(payload)))
        }
    }
}

/// Check whether a RunnerHarnessEvent is a control_request (HITL).
pub fn is_control_request(event: &proto::RunnerHarnessEvent) -> bool {
    matches!(
        event.event.as_ref(),
        Some(proto::runner_harness_event::Event::ToolUse(e)) if e.is_control_request
    )
}
