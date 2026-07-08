/// Adapter registry — tracks which providers are available.
///
/// In the Rust orchestrator, adapter availability is determined by
/// the runner's `RunnerReady.available_providers` field, not by
/// local CLI detection. This module provides utility for routing.
use std::collections::HashSet;

/// Simple registry of available providers (populated from runner ready messages).
#[derive(Debug, Clone, Default)]
pub struct AdapterRegistry {
    pub available: HashSet<String>,
}

impl AdapterRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    /// Get the preferred provider from available ones.
    pub fn get_default(&self) -> &str {
        if self.available.contains("claude") {
            "claude"
        } else if self.available.contains("codex") {
            "codex"
        } else {
            "mock"
        }
    }
}
