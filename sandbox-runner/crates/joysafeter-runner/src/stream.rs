use joysafeter_types::harness::HarnessEvent;

use crate::proto;

pub fn harness_event_to_proto(seq: u64, event: &HarnessEvent) -> proto::RunnerHarnessEvent {
    let timestamp_ms = chrono::Utc::now().timestamp_millis();

    let proto_event = match event {
        HarnessEvent::Text { content } => {
            proto::runner_harness_event::Event::Text(proto::TextEvent {
                content: content.clone(),
            })
        }
        HarnessEvent::Thinking { content } => {
            proto::runner_harness_event::Event::Thinking(proto::ThinkingEvent {
                content: content.clone(),
            })
        }
        HarnessEvent::ToolUse {
            tool,
            call_id,
            input,
            is_control_request,
        } => proto::runner_harness_event::Event::ToolUse(proto::ToolUseEvent {
            tool: tool.clone(),
            call_id: call_id.clone(),
            input_json: input.to_string(),
            is_control_request: *is_control_request,
        }),
        HarnessEvent::ToolResult {
            tool,
            call_id,
            output,
        } => proto::runner_harness_event::Event::ToolResult(proto::ToolResultEvent {
            tool: tool.clone(),
            call_id: call_id.clone(),
            output: output.clone(),
        }),
        HarnessEvent::Error { message } => {
            proto::runner_harness_event::Event::Error(proto::ErrorEvent {
                message: message.clone(),
            })
        }
        HarnessEvent::Status { state } => {
            proto::runner_harness_event::Event::Status(proto::StatusEvent {
                state: state.clone(),
            })
        }
        HarnessEvent::Log { level, message } => {
            proto::runner_harness_event::Event::Log(proto::LogEvent {
                level: level.clone(),
                message: message.clone(),
            })
        }
        HarnessEvent::ModelRequestStart { model } => {
            proto::runner_harness_event::Event::ModelRequestStart(proto::ModelRequestStartEvent {
                model: model.clone(),
            })
        }
        HarnessEvent::ModelRequestEnd {
            model,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_write_tokens,
        } => proto::runner_harness_event::Event::ModelRequestEnd(proto::ModelRequestEndEvent {
            model: model.clone(),
            input_tokens: *input_tokens,
            output_tokens: *output_tokens,
            cache_read_tokens: *cache_read_tokens,
            cache_write_tokens: *cache_write_tokens,
        }),
        HarnessEvent::TaskNotification {
            phase,
            task_id,
            tool_use_id,
            description,
            status,
            summary,
            result,
            output_file,
            last_tool_name,
            total_tokens,
            tool_uses,
            duration_ms,
        } => proto::runner_harness_event::Event::TaskNotification(proto::TaskNotificationEvent {
            phase: phase.clone(),
            task_id: task_id.clone(),
            tool_use_id: tool_use_id.clone(),
            description: description.clone(),
            status: status.clone(),
            summary: summary.clone(),
            result: result.clone(),
            output_file: output_file.clone(),
            last_tool_name: last_tool_name.clone(),
            total_tokens: *total_tokens,
            tool_uses: *tool_uses,
            duration_ms: *duration_ms,
        }),
    };

    proto::RunnerHarnessEvent {
        seq,
        timestamp_ms,
        event: Some(proto_event),
    }
}
