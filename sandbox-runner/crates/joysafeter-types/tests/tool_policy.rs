use joysafeter_types::tool_policy::{
    ToolDecision, ToolInvocation, ToolPolicy, ToolPolicyError, ToolRule,
};

#[test]
fn default_decision_applies_without_matching_rule() {
    let policy = ToolPolicy::new(ToolDecision::Ask, vec![]).expect("valid policy");

    assert_eq!(
        policy.decision_for(&ToolInvocation::builtin("Read")),
        ToolDecision::Ask
    );
}

#[test]
fn exact_mcp_rule_overrides_server_rule() {
    let policy = ToolPolicy::new(
        ToolDecision::Ask,
        vec![
            ToolRule::mcp_server("docs", ToolDecision::Deny).expect("valid server rule"),
            ToolRule::mcp_tool("docs", "search", ToolDecision::Allow).expect("valid tool rule"),
        ],
    )
    .expect("valid policy");

    assert_eq!(
        policy.decision_for(&ToolInvocation::mcp("docs", "search")),
        ToolDecision::Allow
    );
    assert_eq!(
        policy.decision_for(&ToolInvocation::mcp("docs", "write")),
        ToolDecision::Deny
    );
}

#[test]
fn stricter_decision_wins_for_equally_specific_rules() {
    let policy = ToolPolicy::new(
        ToolDecision::Allow,
        vec![
            ToolRule::builtin("Bash", ToolDecision::Allow).expect("valid allow rule"),
            ToolRule::builtin("Bash", ToolDecision::Ask).expect("valid ask rule"),
            ToolRule::builtin("Bash", ToolDecision::Deny).expect("valid deny rule"),
        ],
    )
    .expect("valid policy");

    assert_eq!(
        policy.decision_for(&ToolInvocation::builtin("Bash")),
        ToolDecision::Deny
    );
}

#[test]
fn rules_reject_blank_selector_components() {
    assert_eq!(
        ToolRule::builtin("  ", ToolDecision::Allow).unwrap_err(),
        ToolPolicyError::BlankBuiltinName
    );
    assert_eq!(
        ToolRule::mcp_server("", ToolDecision::Ask).unwrap_err(),
        ToolPolicyError::BlankMcpServerName
    );
    assert_eq!(
        ToolRule::mcp_tool("docs", " ", ToolDecision::Deny).unwrap_err(),
        ToolPolicyError::BlankMcpToolName
    );
}

#[test]
fn policy_reports_whether_interactive_or_denied_decisions_exist() {
    let allow_only = ToolPolicy::new(ToolDecision::Allow, vec![]).expect("valid policy");
    let guarded = ToolPolicy::new(
        ToolDecision::Allow,
        vec![ToolRule::builtin("Bash", ToolDecision::Ask).expect("valid rule")],
    )
    .expect("valid policy");

    assert!(allow_only.is_unconditionally_allow());
    assert!(!guarded.is_unconditionally_allow());
}
