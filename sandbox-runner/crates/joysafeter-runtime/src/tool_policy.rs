use joysafeter_types::harness::HarnessError;
use joysafeter_types::tool_policy::{ToolDecision, ToolInvocation, ToolPolicy};

pub fn claude_permission_mode(
    provider: &str,
    policy: &ToolPolicy,
) -> Result<&'static str, HarnessError> {
    match policy.default_decision() {
        ToolDecision::Allow => Ok("bypassPermissions"),
        ToolDecision::Ask => Ok("default"),
        ToolDecision::Deny => Err(HarnessError::UnsupportedToolPolicy {
            provider: provider.to_string(),
            reason: "a deny-by-default policy cannot be represented by the Claude-compatible CLI"
                .to_string(),
        }),
    }
}

pub fn decision_for_runtime_tool(policy: &ToolPolicy, runtime_name: &str) -> ToolDecision {
    if let Some(rest) = runtime_name.strip_prefix("mcp__") {
        if let Some((server, tool)) = rest.split_once("__") {
            return policy.decision_for(&ToolInvocation::mcp(server, tool));
        }
    }
    let builtin = runtime_name
        .split_once(" (")
        .map(|(name, _)| name)
        .unwrap_or(runtime_name);
    policy.decision_for(&ToolInvocation::builtin(builtin))
}
