//! Pluggable agent identity injection for outbound requests.
//!
//! When an Agent executes a Task, the platform may need to inject identity
//! headers into the sandbox's outbound HTTP requests so downstream services
//! can identify "which agent + on behalf of which user" is calling.
//!
//! This module defines the [`AgentIdentityProvider`] trait. The orchestrator
//! core depends only on this trait — concrete implementations (e.g. JD Agent
//! Identity Protocol) live behind Cargo feature flags or external crates.
//!
//! Default: [`NoopAgentIdentityProvider`] — does nothing; identity injection
//! is disabled unless a provider is explicitly configured.

use async_trait::async_trait;
use serde_json::Value as JsonValue;

// ---------------------------------------------------------------------------
// Public types shared between core and provider implementations
// ---------------------------------------------------------------------------

/// A single target host + the headers to inject on outbound requests to it.
#[derive(Debug, Clone)]
pub struct IdentityEgressTarget {
    /// Target host that triggers injection (matched by Envoy vhost).
    pub host: String,
    /// Port (default 443).
    pub port: u16,
    /// Whether the upstream requires TLS origination.
    pub tls: bool,
    /// Headers to inject (name, value). These are secrets — only live in
    /// Envoy inject_headers, never in sandbox env/secrets.
    pub inject_headers: Vec<(String, String)>,
    /// Headers to strip from the sandbox request before injection
    /// (prevents sandbox from spoofing identity headers).
    pub remove_headers: Vec<String>,
}

/// Resolved identity injection result for one task execution.
#[derive(Debug, Clone, Default)]
pub struct AgentIdentityInjection {
    /// Per-host injection targets. Empty = no identity injection this run.
    pub targets: Vec<IdentityEgressTarget>,
}

/// Context passed to the provider for token resolution.
#[derive(Debug, Clone)]
pub struct IdentityResolveContext {
    /// Agent's unique ID.
    pub agent_id: String,
    /// Session ID (if available).
    pub session_id: String,
    /// Task ID being executed.
    pub task_id: String,
    /// Triggering user's raw identity credential (decrypted from storage).
    /// Provider uses this to bootstrap its token exchange flow.
    /// Empty when `auth_code` is provided instead.
    pub identity_token: String,
    /// One-time authorization code for token exchange (API-key scenario).
    /// When present, the provider should use this to obtain the long-lived
    /// credential instead of `identity_token`.
    pub auth_code: Option<String>,
    /// Triggering user's display name / email (for cache keying).
    pub user_name: String,
    /// Agent-level identity config parsed from metadata (provider-specific).
    pub provider_config: JsonValue,
}

/// Context for cleanup operations.
#[derive(Debug, Clone)]
pub struct IdentityCleanupContext {
    /// Agent ID whose credentials should be cleaned up.
    pub agent_id: String,
    /// If provided, only clean up credentials for this user.
    pub user_name: Option<String>,
}

// ---------------------------------------------------------------------------
// Provider trait
// ---------------------------------------------------------------------------

/// Trait for pluggable agent identity injection.
///
/// Implementations are responsible for:
/// - Parsing agent metadata to determine if/how identity injection is needed
/// - Managing credential lifecycle (caching, refreshing, revoking)
/// - Producing the final headers to inject via Envoy
///
/// The orchestrator core calls these methods during sandbox resolution and
/// agent lifecycle events. Implementations must be `Send + Sync` and safe
/// for concurrent use across tasks.
#[async_trait]
pub trait AgentIdentityProvider: Send + Sync + std::fmt::Debug {
    /// Human-readable provider name (for logging/diagnostics).
    fn name(&self) -> &str;

    /// Whether this provider is active. Returns false → entire injection
    /// pipeline is skipped (zero overhead when disabled).
    fn enabled(&self) -> bool;

    /// Check if the given agent has identity injection configured.
    /// Called during `build_resolve_context()` — should be fast (no I/O).
    ///
    /// Returns true if `agent_metadata` contains valid identity config
    /// that this provider can handle.
    fn has_config(&self, agent_metadata: Option<&JsonValue>) -> bool;

    /// Resolve identity tokens and produce injection targets.
    ///
    /// This is the core method. Called once per sandbox resolution (i.e. per
    /// task start or sandbox reuse). The provider should:
    /// 1. Obtain/cache the long-lived credential (e.g. BotToken)
    /// 2. Exchange for short-lived tokens (e.g. agentToken, SSO ticket)
    /// 3. Return per-host injection headers
    ///
    /// Errors are non-fatal: the orchestrator logs and continues without
    /// identity injection (fail-open). The sandbox still runs.
    async fn resolve(
        &self,
        context: &IdentityResolveContext,
    ) -> anyhow::Result<AgentIdentityInjection>;

    /// Cleanup credentials when an agent is deleted or a user revokes access.
    ///
    /// Implementations should revoke cached tokens and notify the identity
    /// platform. Errors are logged but not propagated.
    async fn cleanup(&self, context: &IdentityCleanupContext);
}

// ---------------------------------------------------------------------------
// Default no-op implementation (open-source default)
// ---------------------------------------------------------------------------

/// No-op provider — identity injection disabled.
///
/// This is the default when no provider feature is enabled. Zero overhead:
/// `enabled()` returns false, so the orchestrator skips the entire pipeline.
#[derive(Debug, Clone, Copy)]
pub struct NoopAgentIdentityProvider;

#[async_trait]
impl AgentIdentityProvider for NoopAgentIdentityProvider {
    fn name(&self) -> &str {
        "noop"
    }

    fn enabled(&self) -> bool {
        false
    }

    fn has_config(&self, _agent_metadata: Option<&JsonValue>) -> bool {
        false
    }

    async fn resolve(
        &self,
        _context: &IdentityResolveContext,
    ) -> anyhow::Result<AgentIdentityInjection> {
        Ok(AgentIdentityInjection::default())
    }

    async fn cleanup(&self, _context: &IdentityCleanupContext) {}
}
