use joysafeter_types::harness::HarnessEvent;
use std::collections::HashMap;

pub struct PiMapped {
    pub events: Vec<HarnessEvent>,
    pub turn_done: bool,
}

pub fn map_pi_event(
    event: &serde_json::Value,
    call_id_to_tool: &mut HashMap<String, String>,
) -> PiMapped {
    let mut events = Vec::new();
    let mut turn_done = false;
    let etype = event.get("type").and_then(|t| t.as_str()).unwrap_or("");

    match etype {
        "message_update" => {
            let ame = event.get("assistantMessageEvent");
            let ame_type = ame
                .and_then(|a| a.get("type"))
                .and_then(|t| t.as_str())
                .unwrap_or("");
            let delta = ame
                .and_then(|a| a.get("delta"))
                .and_then(|d| d.as_str())
                .unwrap_or("");
            match ame_type {
                "text_delta" if !delta.is_empty() => {
                    events.push(HarnessEvent::Text { content: delta.to_string() });
                }
                "thinking_delta" if !delta.is_empty() => {
                    events.push(HarnessEvent::Thinking { content: delta.to_string() });
                }
                _ => {}
            }
        }
        "tool_execution_start" => {
            let tool = event.get("toolName").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let call_id = event.get("toolCallId").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let input = event.get("args").cloned().unwrap_or(serde_json::Value::Null);
            call_id_to_tool.insert(call_id.clone(), tool.clone());
            events.push(HarnessEvent::ToolUse { tool, call_id, input, is_control_request: false });
        }
        "tool_execution_end" => {
            let call_id = event.get("toolCallId").and_then(|t| t.as_str()).unwrap_or("").to_string();
            let tool = event
                .get("toolName")
                .and_then(|t| t.as_str())
                .map(|s| s.to_string())
                .or_else(|| call_id_to_tool.get(&call_id).cloned())
                .unwrap_or_default();
            let result = event.get("result");
            let output = match result {
                Some(serde_json::Value::String(s)) => s.clone(),
                Some(v) => v.to_string(),
                None => String::new(),
            };
            if event.get("isError").and_then(|b| b.as_bool()).unwrap_or(false) {
                events.push(HarnessEvent::Error { message: output.clone() });
            }
            events.push(HarnessEvent::ToolResult { tool, call_id, output });
        }
        "message_end" => {
            if let Some(message) = event.get("message") {
                let model = message.get("model").and_then(|m| m.as_str()).unwrap_or("unknown").to_string();
                if let Some(usage) = message.get("usage") {
                    let g = |k: &str| usage.get(k).and_then(|v| v.as_u64()).unwrap_or(0);
                    events.push(HarnessEvent::ModelRequestEnd {
                        model,
                        input_tokens: g("input"),
                        output_tokens: g("output"),
                        cache_read_tokens: g("cacheRead"),
                        cache_write_tokens: g("cacheWrite"),
                    });
                }
            }
        }
        "agent_settled" => {
            turn_done = true;
        }
        "error" => {
            let msg = event.get("message").and_then(|m| m.as_str()).unwrap_or("pi error").to_string();
            events.push(HarnessEvent::Error { message: msg });
        }
        _ => {}
    }

    PiMapped { events, turn_done }
}

#[cfg(test)]
mod tests {
    use super::*;
    use joysafeter_types::harness::HarnessEvent;

    fn map(v: serde_json::Value) -> PiMapped {
        let mut m = HashMap::new();
        map_pi_event(&v, &mut m)
    }

    #[test]
    fn text_delta_maps_to_text() {
        let m = map(serde_json::json!({
            "type": "message_update",
            "assistantMessageEvent": { "type": "text_delta", "delta": "hello" }
        }));
        assert!(matches!(&m.events[0], HarnessEvent::Text { content } if content == "hello"));
    }

    #[test]
    fn thinking_delta_maps_to_thinking() {
        let m = map(serde_json::json!({
            "type": "message_update",
            "assistantMessageEvent": { "type": "thinking_delta", "delta": "hmm" }
        }));
        assert!(matches!(&m.events[0], HarnessEvent::Thinking { content } if content == "hmm"));
    }

    #[test]
    fn tool_execution_start_maps_to_tool_use() {
        let m = map(serde_json::json!({
            "type": "tool_execution_start",
            "toolCallId": "call_1", "toolName": "bash",
            "args": { "command": "ls" }
        }));
        match &m.events[0] {
            HarnessEvent::ToolUse { tool, call_id, is_control_request, .. } => {
                assert_eq!(tool, "bash");
                assert_eq!(call_id, "call_1");
                assert!(!is_control_request);
            }
            other => panic!("expected ToolUse, got {other:?}"),
        }
    }

    #[test]
    fn tool_execution_end_maps_to_tool_result() {
        let mut cmap = HashMap::new();
        map_pi_event(&serde_json::json!({
            "type": "tool_execution_start",
            "toolCallId": "call_1", "toolName": "bash", "args": {}
        }), &mut cmap);
        let m = map_pi_event(&serde_json::json!({
            "type": "tool_execution_end",
            "toolCallId": "call_1", "toolName": "bash",
            "result": "file.txt", "isError": false
        }), &mut cmap);
        match &m.events[0] {
            HarnessEvent::ToolResult { tool, call_id, output } => {
                assert_eq!(tool, "bash");
                assert_eq!(call_id, "call_1");
                assert!(output.contains("file.txt"));
            }
            other => panic!("expected ToolResult, got {other:?}"),
        }
    }

    #[test]
    fn message_end_usage_maps_to_model_request_end() {
        let m = map(serde_json::json!({
            "type": "message_end",
            "message": {
                "model": "deepseek/deepseek-chat",
                "usage": { "input": 10, "output": 5, "cacheRead": 2, "cacheWrite": 1 }
            }
        }));
        let mre = m.events.iter().find(|e| matches!(e, HarnessEvent::ModelRequestEnd { .. }))
            .expect("expected ModelRequestEnd");
        match mre {
            HarnessEvent::ModelRequestEnd { model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens } => {
                assert_eq!(model, "deepseek/deepseek-chat");
                assert_eq!(*input_tokens, 10);
                assert_eq!(*output_tokens, 5);
                assert_eq!(*cache_read_tokens, 2);
                assert_eq!(*cache_write_tokens, 1);
            }
            _ => unreachable!(),
        }
    }

    #[test]
    fn agent_settled_sets_turn_done() {
        let m = map(serde_json::json!({ "type": "agent_settled" }));
        assert!(m.turn_done);
    }

    #[test]
    fn unknown_event_is_ignored() {
        let m = map(serde_json::json!({ "type": "queue_update", "foo": 1 }));
        assert!(m.events.is_empty());
        assert!(!m.turn_done);
    }
}
