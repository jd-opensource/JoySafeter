use async_trait::async_trait;
use joysafeter_types::harness::{
    HarnessAdapter, HarnessError, HarnessEvent, HarnessInput, HarnessResult, HarnessResultStatus,
    RunningHarness,
};
use joysafeter_types::token_usage::TokenUsage;
use std::path::Path;
use std::sync::Arc;
use tokio::sync::{mpsc, oneshot, watch, Mutex};

struct MockControl {
    input_tx: mpsc::Sender<String>,
    cancel_tx: watch::Sender<bool>,
}

pub struct MockAdapter {
    provider: String,
}

impl MockAdapter {
    pub fn new(provider: impl Into<String>) -> Self {
        Self {
            provider: provider.into(),
        }
    }
}

#[async_trait]
impl HarnessAdapter for MockAdapter {
    async fn start(
        &self,
        input: HarnessInput,
        _cwd: &Path,
    ) -> Result<RunningHarness, HarnessError> {
        let (event_tx, event_rx) = mpsc::channel(256);
        let (result_tx, result_rx) = oneshot::channel();
        let (input_tx, mut input_rx) = mpsc::channel::<String>(32);
        let (cancel_tx, mut cancel_rx) = watch::channel(false);

        let prompt = input.prompt;
        let session_id = input.session_id;
        let provider = self.provider.clone();
        tokio::spawn(async move {
            let start = std::time::Instant::now();
            let mut usage = TokenUsage::default();
            usage.input_tokens = 1;

            let resumed_prompt = prompt.contains("User approved tool call event")
                || prompt.contains("Tool result received for tool call event");

            if resumed_prompt {
                let _ = event_tx
                    .send(HarnessEvent::Text {
                        content: format!("[mock:{provider}] resumed"),
                    })
                    .await;
                let _ = result_tx.send(HarnessResult {
                    status: HarnessResultStatus::Completed,
                    output: "MOCK_RESUMED".to_string(),
                    error: None,
                    session_id,
                    usage,
                    duration: start.elapsed(),
                });
                return;
            }

            let _ = event_tx
                .send(HarnessEvent::Status {
                    state: "running".to_string(),
                })
                .await;
            let _ = event_tx
                .send(HarnessEvent::ToolUse {
                    tool: "mock_tool".to_string(),
                    call_id: "mock_call_1".to_string(),
                    input: serde_json::json!({"prompt": prompt}),
                    is_control_request: false,
                })
                .await;

            let next = tokio::select! {
                _ = cancel_rx.changed() => None,
                v = input_rx.recv() => v,
            };

            match next {
                Some(content) => {
                    usage.output_tokens = 1;
                    let _ = event_tx
                        .send(HarnessEvent::ToolResult {
                            tool: "mock_tool".to_string(),
                            call_id: "mock_call_1".to_string(),
                            output: content.clone(),
                        })
                        .await;
                    let _ = event_tx
                        .send(HarnessEvent::Text {
                            content: format!("[mock:{provider}] completed"),
                        })
                        .await;
                    let _ = result_tx.send(HarnessResult {
                        status: HarnessResultStatus::Completed,
                        output: format!("MOCK_COMPLETED: {content}"),
                        error: None,
                        session_id,
                        usage,
                        duration: start.elapsed(),
                    });
                }
                None => {
                    let _ = result_tx.send(HarnessResult {
                        status: HarnessResultStatus::Aborted,
                        output: String::new(),
                        error: Some("mock cancelled".to_string()),
                        session_id,
                        usage,
                        duration: start.elapsed(),
                    });
                }
            }
        });

        Ok(RunningHarness {
            events: event_rx,
            result: result_rx,
            child: None,
            input: Some(Box::new(Arc::new(Mutex::new(MockControl {
                input_tx,
                cancel_tx,
            })))),
        })
    }

    async fn cancel(&self, harness: &mut RunningHarness) -> Result<(), HarnessError> {
        let Some(any) = harness.input.as_ref() else {
            return Ok(());
        };
        let Some(control) = any.downcast_ref::<Arc<Mutex<MockControl>>>() else {
            return Ok(());
        };
        let guard = control.lock().await;
        let _ = guard.cancel_tx.send(true);
        Ok(())
    }

    async fn send_input(
        &self,
        harness: &mut RunningHarness,
        content: String,
    ) -> Result<(), HarnessError> {
        let Some(any) = harness.input.as_ref() else {
            return Err(HarnessError::UnsupportedInput);
        };
        let Some(control) = any.downcast_ref::<Arc<Mutex<MockControl>>>() else {
            return Err(HarnessError::UnsupportedInput);
        };
        let guard = control.lock().await;
        guard
            .input_tx
            .send(content)
            .await
            .map_err(|e| HarnessError::StartFailed(format!("mock input send failed: {e}")))?;
        Ok(())
    }

    fn provider(&self) -> &str {
        &self.provider
    }

    async fn is_available(&self) -> bool {
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use joysafeter_types::harness::HarnessInput;
    use std::collections::HashMap;
    use std::time::Duration;

    fn input(prompt: &str) -> HarnessInput {
        HarnessInput {
            prompt: prompt.to_string(),
            system_prompt: None,
            session_id: Some("mock_session".to_string()),
            model: None,
            max_turns: None,
            timeout: Duration::from_secs(30),
            env: HashMap::new(),
            secrets: HashMap::new(),
            mcp_configs: vec![],
            permission_mode: "default".to_string(),
        }
    }

    #[tokio::test]
    async fn mock_adapter_accepts_send_input_and_completes() {
        let adapter = MockAdapter::new("claude");
        let mut running = adapter
            .start(input("hello"), Path::new("."))
            .await
            .expect("start mock");

        let mut saw_tool_use = false;
        for _ in 0..4 {
            if let Some(HarnessEvent::ToolUse { .. }) = running.events.recv().await {
                saw_tool_use = true;
                break;
            }
        }
        assert!(saw_tool_use, "expected tool use event");

        adapter
            .send_input(&mut running, "approved".to_string())
            .await
            .expect("send input");

        let result = running.result.await.expect("result");
        assert_eq!(result.status, HarnessResultStatus::Completed);
        assert!(result.output.contains("MOCK_COMPLETED"));
    }
}
