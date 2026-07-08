/// Harness adapter abstraction — defines the interface for running
/// agent CLI tools (Claude, Codex, etc.).
///
/// In the orchestrator, the adapter runs INSIDE the sandbox-runner,
/// not in the orchestrator itself. The orchestrator only needs the
/// adapter metadata (provider name, availability) for routing decisions.
/// Actual execution happens via the gRPC protocol.

/// Known harness provider names.
pub const PROVIDER_CLAUDE: &str = "claude";
pub const PROVIDER_CODEX: &str = "codex";
pub const PROVIDER_MOCK: &str = "mock";
