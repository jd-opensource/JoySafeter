pub mod claude;
pub mod claude_project_config;
pub mod codex;
pub mod mock;
pub mod native;
pub mod pi;
pub mod tool_policy;

use joysafeter_types::harness::{HarnessAdapter, HarnessResultStatus};
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Arc;

pub(crate) fn finish_turn(
    aborted: bool,
    error: Option<String>,
) -> (HarnessResultStatus, Option<String>) {
    if aborted {
        (HarnessResultStatus::Aborted, None)
    } else if let Some(error) = error {
        (HarnessResultStatus::Failed, Some(error))
    } else {
        (HarnessResultStatus::Completed, None)
    }
}

/// Extract an error message from a value that is either a bare string or an
/// object carrying a `message` string field.
pub(crate) fn error_value_message(error: &Value) -> Option<String> {
    match error {
        Value::String(message) if !message.trim().is_empty() => Some(message.clone()),
        Value::Object(_) => error
            .get("message")
            .and_then(Value::as_str)
            .filter(|message| !message.trim().is_empty())
            .map(ToOwned::to_owned),
        _ => None,
    }
}

pub(crate) fn sdk_result_error(raw: &Value) -> Option<String> {
    let subtype = raw.get("subtype").and_then(Value::as_str).unwrap_or("");
    let is_error = raw
        .get("is_error")
        .and_then(Value::as_bool)
        .unwrap_or_else(|| subtype.starts_with("error_"));
    if !is_error {
        return None;
    }

    let errors = raw
        .get("errors")
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(Value::as_str)
                .filter(|message| !message.trim().is_empty())
                .collect::<Vec<_>>()
                .join("; ")
        })
        .filter(|message| !message.is_empty());
    errors
        .or_else(|| raw.get("error").and_then(error_value_message))
        .or_else(|| {
            raw.get("result")
                .and_then(Value::as_str)
                .filter(|message| !message.trim().is_empty())
                .map(ToOwned::to_owned)
        })
        .or_else(|| {
            Some(if subtype.is_empty() {
                "agent turn failed".to_string()
            } else {
                format!("agent turn failed: {subtype}")
            })
        })
}

pub struct AdapterRegistry {
    adapters: HashMap<String, Arc<dyn HarnessAdapter>>,
}

impl AdapterRegistry {
    pub async fn discover() -> Self {
        let mut adapters: HashMap<String, Arc<dyn HarnessAdapter>> = HashMap::new();

        let mock_enabled = std::env::var("JOYSAFETER_MOCK_ADAPTER")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

        if mock_enabled {
            adapters.insert(
                "claude".to_string(),
                Arc::new(mock::MockAdapter::new("claude")),
            );
            adapters.insert(
                "codex".to_string(),
                Arc::new(mock::MockAdapter::new("codex")),
            );
            adapters.insert(
                "native".to_string(),
                Arc::new(mock::MockAdapter::new("native")),
            );
            adapters.insert("pi".to_string(), Arc::new(mock::MockAdapter::new("pi")));
        } else {
            let claude = claude::ClaudeAdapter::new();
            if claude.is_available().await {
                adapters.insert("claude".to_string(), Arc::new(claude));
            }

            let native_adapter = native::NativeAdapter::new();
            if native_adapter.is_available().await {
                adapters.insert("native".to_string(), Arc::new(native_adapter));
            }

            let codex = codex::CodexAdapter::new();
            if codex.is_available().await {
                adapters.insert("codex".to_string(), Arc::new(codex));
            }

            let pi_adapter = pi::PiAdapter::new();
            if pi_adapter.is_available().await {
                adapters.insert("pi".to_string(), Arc::new(pi_adapter));
            }
        }

        Self { adapters }
    }

    pub fn get(&self, provider: &str) -> Option<Arc<dyn HarnessAdapter>> {
        self.adapters.get(provider).cloned()
    }

    pub fn provider_names(&self) -> Vec<String> {
        self.adapters.keys().cloned().collect()
    }

    pub fn is_empty(&self) -> bool {
        self.adapters.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use joysafeter_types::harness::HarnessResultStatus;

    #[test]
    fn explicit_turn_error_produces_failed_result() {
        let (status, error) = super::finish_turn(false, Some("provider failed".to_string()));
        assert_eq!(status, HarnessResultStatus::Failed);
        assert_eq!(error.as_deref(), Some("provider failed"));
    }
}
