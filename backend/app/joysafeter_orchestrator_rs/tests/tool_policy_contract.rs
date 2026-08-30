use std::fs;
use std::path::PathBuf;

use joysafeter_orchestrator::kernel::tool_policy::{
    ToolDecision, ToolPolicy, ToolPolicyError, ToolSelector,
};

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .unwrap_or_else(|error| panic!("read {path}: {error}"))
}

#[test]
fn agent_tools_compile_to_provider_neutral_policy() {
    let tools = serde_json::json!([
        {
            "type": "agent_toolset_20260401",
            "default_config": {"permission_policy": {"type": "always_ask"}},
            "configs": [
                {"name": "Bash", "enabled": true, "permission_policy": {"type": "always_allow"}},
                {"name": "Write", "enabled": false}
            ]
        },
        {
            "type": "mcp_toolset",
            "mcp_server_name": "docs",
            "default_config": {"permission_policy": {"type": "always_ask"}},
            "configs": [
                {"name": "search", "enabled": true, "permission_policy": {"type": "always_allow"}}
            ]
        }
    ]);

    let policy = ToolPolicy::from_agent_tools(Some(&tools)).expect("valid policy");

    assert_eq!(policy.default_decision(), ToolDecision::Ask);
    assert!(policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Builtin {
                name: "Bash".into(),
            }
            && rule.decision == ToolDecision::Allow
    }));
    assert!(policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Builtin {
                name: "Write".into(),
            }
            && rule.decision == ToolDecision::Deny
    }));
    assert!(policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Mcp {
                server: "docs".into(),
                tool: None,
            }
            && rule.decision == ToolDecision::Ask
    }));
    assert!(policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Mcp {
                server: "docs".into(),
                tool: Some("search".into()),
            }
            && rule.decision == ToolDecision::Allow
    }));
}

#[test]
fn missing_builtin_toolset_defaults_fail_closed() {
    let policy = ToolPolicy::from_agent_tools(Some(&serde_json::json!([]))).expect("valid policy");

    assert_eq!(policy.default_decision(), ToolDecision::Ask);
}

#[test]
fn builtin_toolset_without_explicit_default_preserves_managed_default() {
    let tools = serde_json::json!([{"type": "agent_toolset_20260401"}]);

    let policy = ToolPolicy::from_agent_tools(Some(&tools)).expect("valid policy");

    assert_eq!(policy.default_decision(), ToolDecision::Allow);
}

#[test]
fn invalid_policy_values_fail_closed() {
    let tools = serde_json::json!([{
        "type": "agent_toolset_20260401",
        "default_config": {"permission_policy": {"type": "trust_everything"}}
    }]);

    assert_eq!(
        ToolPolicy::from_agent_tools(Some(&tools)).unwrap_err(),
        ToolPolicyError::UnsupportedDecision("trust_everything".into())
    );
}

#[test]
fn multiple_builtin_defaults_are_rejected() {
    let tools = serde_json::json!([
        {"type": "agent_toolset_20260401"},
        {"type": "agent_toolset_20260401"}
    ]);

    assert_eq!(
        ToolPolicy::from_agent_tools(Some(&tools)).unwrap_err(),
        ToolPolicyError::DuplicateBuiltinToolset
    );
}

#[test]
fn kernel_policy_is_transport_neutral_and_grpc_owns_wire_projection() {
    let kernel = source("src/kernel/tool_policy.rs");
    let grpc = source("src/grpc/tool_policy.rs");

    for forbidden in ["crate::grpc", "proto::", "to_proto"] {
        assert!(
            !kernel.contains(forbidden),
            "kernel tool policy depends on transport detail {forbidden}"
        );
    }
    for required in ["pub(crate) fn encode", "proto::ToolPolicy", "encode_rule"] {
        assert!(
            grpc.contains(required),
            "gRPC tool policy adapter misses {required}"
        );
    }
}
