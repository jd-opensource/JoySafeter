use thiserror::Error;

use crate::kernel::tool_policy::{ToolDecision, ToolPolicy};

/// Data-driven engine adapter registry.
///
/// Engine-specific (claude / codex / native / pi) decisions that were previously
/// scattered across multiple match arms are now encoded in a single registry.
/// Adding a new engine adapter is a table entry rather than touching multiple
/// files.

/// Specification for a single engine adapter.
pub struct EngineSpec {
    /// Engine kind identifier (matches `input.provider`).
    pub engine_kind: &'static str,

    /// Whether conversation history injection applies (vs harness resume).
    pub injects_conversation_history: bool,

    /// Protocols this engine can execute, using canonical Catalog IDs.
    pub supported_protocol_ids: &'static [&'static str],

    /// Whether the runtime can consume MCP server configuration.
    pub supports_mcp_servers: bool,

    /// Whether the runtime can register platform custom tools.
    pub supports_custom_tools: bool,

    /// Whether the runtime consumes materialized Skill archives.
    pub supports_skills: bool,

    /// Tool-policy shape that the runtime can enforce.
    pub tool_policy_support: ToolPolicySupport,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolPolicySupport {
    Structured,
    ClaudeCompatible,
    UnconditionalAllow,
}

/// Returns the ordered registry of engine adapters.
pub fn engine_registry() -> &'static [EngineSpec] {
    static REGISTRY: &[EngineSpec] = &[
        EngineSpec {
            engine_kind: "claude",
            injects_conversation_history: true,
            supported_protocol_ids: &["anthropic_messages"],
            supports_mcp_servers: true,
            supports_custom_tools: true,
            supports_skills: true,
            tool_policy_support: ToolPolicySupport::ClaudeCompatible,
        },
        EngineSpec {
            engine_kind: "codex",
            injects_conversation_history: true,
            supported_protocol_ids: &["openai_responses"],
            supports_mcp_servers: true,
            supports_custom_tools: false,
            supports_skills: true,
            tool_policy_support: ToolPolicySupport::Structured,
        },
        EngineSpec {
            engine_kind: "native",
            injects_conversation_history: true,
            supported_protocol_ids: &["anthropic_messages", "openai_responses", "chat_completions"],
            supports_mcp_servers: true,
            supports_custom_tools: true,
            supports_skills: true,
            tool_policy_support: ToolPolicySupport::ClaudeCompatible,
        },
        EngineSpec {
            engine_kind: "pi",
            injects_conversation_history: true,
            supported_protocol_ids: &["anthropic_messages", "openai_responses", "chat_completions"],
            supports_mcp_servers: false,
            supports_custom_tools: false,
            supports_skills: true,
            tool_policy_support: ToolPolicySupport::UnconditionalAllow,
        },
    ];
    REGISTRY
}

/// Look up the engine spec by kind. Returns `None` for unknown engines.
pub fn engine_spec(engine_kind: &str) -> Option<&'static EngineSpec> {
    engine_registry()
        .iter()
        .find(|s| s.engine_kind == engine_kind)
}

pub fn validate_runtime_capabilities(
    engine_kind: &str,
    tool_policy: &ToolPolicy,
    has_mcp_servers: bool,
    has_custom_tools: bool,
) -> Result<(), EngineCapabilityError> {
    let spec = engine_spec(engine_kind).ok_or_else(|| EngineCapabilityError::UnknownEngine {
        engine_kind: engine_kind.to_string(),
    })?;

    if has_mcp_servers && !spec.supports_mcp_servers {
        return Err(EngineCapabilityError::UnsupportedCapability {
            engine_kind: engine_kind.to_string(),
            capability: "mcp_servers",
        });
    }
    if has_custom_tools && !spec.supports_custom_tools {
        return Err(EngineCapabilityError::UnsupportedCapability {
            engine_kind: engine_kind.to_string(),
            capability: "custom_tools",
        });
    }

    match spec.tool_policy_support {
        ToolPolicySupport::Structured => Ok(()),
        ToolPolicySupport::ClaudeCompatible
            if tool_policy.default_decision() == ToolDecision::Deny =>
        {
            Err(EngineCapabilityError::UnsupportedToolPolicy {
                engine_kind: engine_kind.to_string(),
                reason:
                    "a deny-by-default policy cannot be represented by the Claude-compatible CLI",
            })
        }
        ToolPolicySupport::UnconditionalAllow
            if tool_policy.requires_runtime_enforcement()
                && !tool_policy.is_unconditionally_allow() =>
        {
            Err(EngineCapabilityError::UnsupportedToolPolicy {
                engine_kind: engine_kind.to_string(),
                reason: "interactive or denied tool decisions cannot be enforced by this runtime",
            })
        }
        _ => Ok(()),
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum EngineCapabilityError {
    #[error("unknown runtime engine: {engine_kind}")]
    UnknownEngine { engine_kind: String },
    #[error("capability {capability} is unsupported by {engine_kind}")]
    UnsupportedCapability {
        engine_kind: String,
        capability: &'static str,
    },
    #[error("tool policy is unsupported by {engine_kind}: {reason}")]
    UnsupportedToolPolicy {
        engine_kind: String,
        reason: &'static str,
    },
}

#[cfg(test)]
mod tests {
    use crate::kernel::llm_catalog::catalog;
    use crate::kernel::tool_policy::{ToolDecision, ToolPolicy};

    #[test]
    fn pi_engine_is_registered() {
        assert!(super::engine_spec("pi").is_some());
    }

    #[test]
    fn pi_supports_skills_but_not_mcp_or_custom_tools() {
        let spec = super::engine_spec("pi").expect("Pi engine must be registered");

        assert!(spec.supports_skills);
        assert!(!spec.supports_mcp_servers);
        assert!(!spec.supports_custom_tools);
    }

    #[test]
    fn pi_accepts_a_model_only_request_without_tool_policy_enforcement() {
        let policy = ToolPolicy::from_agent_tools(Some(&serde_json::json!([])))
            .expect("empty tool declaration is valid");

        super::validate_runtime_capabilities("pi", &policy, false, false)
            .expect("model-only Pi execution has no tool policy to enforce");
    }

    #[test]
    fn engine_protocol_matrix_matches_catalog() {
        let catalog = catalog().expect("catalog must parse");

        for engine in &catalog.engines {
            let spec = super::engine_spec(&engine.id).expect("catalog engine must have adapter");
            assert_eq!(
                spec.supported_protocol_ids,
                engine
                    .supported_protocol_ids
                    .iter()
                    .map(String::as_str)
                    .collect::<Vec<_>>()
            );
        }
        assert_eq!(super::engine_registry().len(), catalog.engines.len());
    }

    #[test]
    fn pi_capabilities_fail_before_runner_dispatch() {
        let policy = ToolPolicy::from_agent_tools(Some(&serde_json::json!([
            {"type": "agent_toolset_20260401"}
        ])))
        .expect("valid policy");

        let error = super::validate_runtime_capabilities("pi", &policy, true, false)
            .expect_err("Pi must reject MCP before runner dispatch");

        assert!(error.to_string().contains("mcp_servers"));
    }

    #[test]
    fn codex_capabilities_fail_before_runner_dispatch() {
        let policy = ToolPolicy::from_agent_tools(Some(&serde_json::json!([
            {"type": "agent_toolset_20260401"}
        ])))
        .expect("valid policy");

        let error = super::validate_runtime_capabilities("codex", &policy, false, true)
            .expect_err("Codex must reject custom tools before runner dispatch");

        assert!(error.to_string().contains("custom_tools"));
    }

    #[test]
    fn claude_compatible_capabilities_reject_deny_default() {
        let policy = ToolPolicy::from_agent_tools(Some(&serde_json::json!([{
            "type": "agent_toolset_20260401",
            "default_config": {"enabled": false}
        }])))
        .expect("valid policy");
        assert_eq!(policy.default_decision(), ToolDecision::Deny);

        let error = super::validate_runtime_capabilities("claude", &policy, false, false)
            .expect_err("Claude must reject deny-by-default before runner dispatch");

        assert!(error.to_string().contains("deny-by-default"));
    }
}
