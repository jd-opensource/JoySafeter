//! JoySafeter Orchestrator — library re-exports for plugin crates.
//!
//! Exposes selected modules so plugin crates (e.g. `jd-agent-identity`)
//! can implement traits defined here without duplicating type definitions.

#[path = "kernel"]
pub mod kernel {
    pub mod agent_identity_provider;
}
