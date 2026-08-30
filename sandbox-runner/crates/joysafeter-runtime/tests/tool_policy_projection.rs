use joysafeter_runtime::tool_policy::{claude_permission_mode, decision_for_runtime_tool};
use joysafeter_types::tool_policy::{ToolDecision, ToolPolicy, ToolRule};

#[test]
fn claude_mode_projects_only_supported_defaults() {
    let allow = ToolPolicy::new(ToolDecision::Allow, vec![]).expect("valid policy");
    let ask = ToolPolicy::new(ToolDecision::Ask, vec![]).expect("valid policy");
    let deny = ToolPolicy::new(ToolDecision::Deny, vec![]).expect("valid policy");

    assert_eq!(
        claude_permission_mode("claude", &allow).unwrap(),
        "bypassPermissions"
    );
    assert_eq!(claude_permission_mode("native", &ask).unwrap(), "default");
    assert!(claude_permission_mode("claude", &deny).is_err());
}

#[test]
fn runtime_tool_names_resolve_without_widening_mcp_rules() {
    let policy = ToolPolicy::new(
        ToolDecision::Ask,
        vec![
            ToolRule::builtin("Bash", ToolDecision::Allow).expect("valid builtin"),
            ToolRule::mcp_server("docs", ToolDecision::Deny).expect("valid server"),
            ToolRule::mcp_tool("docs", "search", ToolDecision::Allow).expect("valid tool"),
        ],
    )
    .expect("valid policy");

    assert_eq!(
        decision_for_runtime_tool(&policy, "Bash (git)"),
        ToolDecision::Allow
    );
    assert_eq!(
        decision_for_runtime_tool(&policy, "mcp__docs__search"),
        ToolDecision::Allow
    );
    assert_eq!(
        decision_for_runtime_tool(&policy, "mcp__docs__*"),
        ToolDecision::Deny
    );
    assert_eq!(
        decision_for_runtime_tool(&policy, "mcp__other__search"),
        ToolDecision::Ask
    );
}
