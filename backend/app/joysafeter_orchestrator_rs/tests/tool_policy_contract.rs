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
fn nullable_builtin_item_policy_inherits_toolset_default() {
    let tools = serde_json::json!([{
        "type": "agent_toolset_20260401",
        "default_config": {
            "enabled": true,
            "permission_policy": {"type": "always_allow"}
        },
        "configs": [
            {"name": "Bash", "enabled": true, "permission_policy": null}
        ]
    }]);

    let policy = ToolPolicy::from_agent_tools(Some(&tools))
        .expect("nullable item policy must inherit the toolset default");

    assert!(policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Builtin {
                name: "Bash".into(),
            }
            && rule.decision == ToolDecision::Allow
    }));
}

#[test]
fn nullable_toolset_default_uses_domain_default() {
    let builtin = serde_json::json!([{
        "type": "agent_toolset_20260401",
        "default_config": null,
        "configs": []
    }]);
    let mcp = serde_json::json!([{
        "type": "mcp_toolset",
        "mcp_server_name": "docs",
        "default_config": null,
        "configs": []
    }]);

    let builtin_policy = ToolPolicy::from_agent_tools(Some(&builtin))
        .expect("nullable builtin default must use allow");
    let mcp_policy =
        ToolPolicy::from_agent_tools(Some(&mcp)).expect("nullable MCP default must use ask");

    assert_eq!(builtin_policy.default_decision(), ToolDecision::Allow);
    assert!(mcp_policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Mcp {
                server: "docs".into(),
                tool: None,
            }
            && rule.decision == ToolDecision::Ask
    }));
}

#[test]
fn nullable_mcp_item_policy_inherits_server_default() {
    let tools = serde_json::json!([{
        "type": "mcp_toolset",
        "mcp_server_name": "docs",
        "default_config": {
            "enabled": true,
            "permission_policy": {"type": "always_allow"}
        },
        "configs": [
            {"name": "search", "enabled": true, "permission_policy": null}
        ]
    }]);

    let policy = ToolPolicy::from_agent_tools(Some(&tools))
        .expect("nullable MCP item policy must inherit the server default");

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
fn disabled_builtin_toolset_denies_unlisted_tools_but_allows_explicit_overrides() {
    let tools = serde_json::json!([{
        "type": "agent_toolset_20260401",
        "default_config": {
            "enabled": false,
            "permission_policy": {"type": "always_allow"}
        },
        "configs": [
            {"name": "Read", "enabled": true, "permission_policy": null}
        ]
    }]);

    let policy = ToolPolicy::from_agent_tools(Some(&tools))
        .expect("disabled toolset with an explicit enabled rule must compile");

    assert_eq!(policy.default_decision(), ToolDecision::Deny);
    assert!(policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Builtin {
                name: "Read".into(),
            }
            && rule.decision == ToolDecision::Allow
    }));
}

#[test]
fn disabled_mcp_toolset_denies_server_but_allows_explicit_tool_override() {
    let tools = serde_json::json!([{
        "type": "mcp_toolset",
        "mcp_server_name": "docs",
        "default_config": {
            "enabled": false,
            "permission_policy": {"type": "always_allow"}
        },
        "configs": [
            {"name": "search", "enabled": true, "permission_policy": null}
        ]
    }]);

    let policy = ToolPolicy::from_agent_tools(Some(&tools))
        .expect("disabled MCP server with an explicit enabled tool must compile");

    assert!(policy.rules().iter().any(|rule| {
        rule.selector
            == ToolSelector::Mcp {
                server: "docs".into(),
                tool: None,
            }
            && rule.decision == ToolDecision::Deny
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
fn non_boolean_toolset_enabled_flag_remains_invalid() {
    let tools = serde_json::json!([{
        "type": "agent_toolset_20260401",
        "default_config": {
            "enabled": "false",
            "permission_policy": {"type": "always_allow"}
        }
    }]);

    assert_eq!(
        ToolPolicy::from_agent_tools(Some(&tools)).unwrap_err(),
        ToolPolicyError::InvalidEnabledFlag
    );
}

#[test]
fn non_null_non_object_permission_policy_remains_invalid() {
    let tools = serde_json::json!([{
        "type": "agent_toolset_20260401",
        "configs": [
            {"name": "Bash", "enabled": true, "permission_policy": "always_allow"}
        ]
    }]);

    assert_eq!(
        ToolPolicy::from_agent_tools(Some(&tools)).unwrap_err(),
        ToolPolicyError::InvalidPermissionPolicyShape
    );
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
fn duplicate_mcp_toolsets_are_rejected_as_ambiguous() {
    let tools = serde_json::json!([
        {"type": "mcp_toolset", "mcp_server_name": "docs"},
        {"type": "mcp_toolset", "mcp_server_name": "docs"}
    ]);

    assert!(ToolPolicy::from_agent_tools(Some(&tools)).is_err());
}

#[test]
fn duplicate_rules_within_a_toolset_are_rejected_as_ambiguous() {
    let tools = serde_json::json!([{
        "type": "agent_toolset_20260401",
        "configs": [
            {"name": "Bash", "enabled": true},
            {"name": "Bash", "enabled": false}
        ]
    }]);

    assert!(ToolPolicy::from_agent_tools(Some(&tools)).is_err());
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
