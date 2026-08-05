pub mod claude;
pub mod codex;
pub mod mock;
pub mod native;

use joysafeter_types::harness::HarnessAdapter;
use std::collections::HashMap;
use std::sync::Arc;

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
