use anyhow::{anyhow, bail};
use joysafeter_types::tool_policy::{ToolDecision, ToolPolicy, ToolRule};

use crate::proto;

pub fn decode(policy: Option<proto::ToolPolicy>) -> anyhow::Result<ToolPolicy> {
    let policy = policy.ok_or_else(|| anyhow!("tool_policy is required"))?;
    let default_decision =
        decode_decision(policy.default_decision, "tool_policy.default_decision")?;
    let rules = policy
        .rules
        .into_iter()
        .enumerate()
        .map(|(index, rule)| {
            decode_rule(rule).map_err(|error| anyhow!("tool_policy.rules[{index}]: {error}"))
        })
        .collect::<anyhow::Result<Vec<_>>>()?;
    ToolPolicy::new(default_decision, rules).map_err(Into::into)
}

fn decode_rule(rule: proto::ToolRule) -> anyhow::Result<ToolRule> {
    let decision = decode_decision(rule.decision, "decision")?;
    match rule
        .selector
        .ok_or_else(|| anyhow!("selector is required"))?
    {
        proto::tool_rule::Selector::BuiltinName(name) => {
            ToolRule::builtin(name, decision).map_err(Into::into)
        }
        proto::tool_rule::Selector::Mcp(selector) => match selector.tool_name {
            Some(tool_name) => {
                ToolRule::mcp_tool(selector.server_name, tool_name, decision).map_err(Into::into)
            }
            None => ToolRule::mcp_server(selector.server_name, decision).map_err(Into::into),
        },
    }
}

fn decode_decision(value: i32, field: &str) -> anyhow::Result<ToolDecision> {
    match proto::ToolDecision::try_from(value) {
        Ok(proto::ToolDecision::Allow) => Ok(ToolDecision::Allow),
        Ok(proto::ToolDecision::Ask) => Ok(ToolDecision::Ask),
        Ok(proto::ToolDecision::Deny) => Ok(ToolDecision::Deny),
        Ok(proto::ToolDecision::Unspecified) => bail!("{field} must be specified"),
        Err(_) => bail!("{field} contains unknown enum value {value}"),
    }
}

#[cfg(test)]
mod tests {
    use joysafeter_types::tool_policy::{ToolDecision, ToolInvocation};

    use crate::proto;

    #[test]
    fn decodes_structured_tool_policy() {
        let wire = proto::ToolPolicy {
            default_decision: proto::ToolDecision::Ask as i32,
            rules: vec![
                proto::ToolRule {
                    decision: proto::ToolDecision::Deny as i32,
                    selector: Some(proto::tool_rule::Selector::BuiltinName("Bash".into())),
                },
                proto::ToolRule {
                    decision: proto::ToolDecision::Allow as i32,
                    selector: Some(proto::tool_rule::Selector::Mcp(proto::McpToolSelector {
                        server_name: "docs".into(),
                        tool_name: Some("search".into()),
                    })),
                },
            ],
        };

        let policy = super::decode(Some(wire)).expect("valid wire policy");

        assert_eq!(
            policy.decision_for(&ToolInvocation::builtin("Bash")),
            ToolDecision::Deny
        );
        assert_eq!(
            policy.decision_for(&ToolInvocation::mcp("docs", "search")),
            ToolDecision::Allow
        );
        assert_eq!(
            policy.decision_for(&ToolInvocation::mcp("docs", "write")),
            ToolDecision::Ask
        );
    }

    #[test]
    fn rejects_missing_or_unspecified_policy() {
        assert!(super::decode(None)
            .unwrap_err()
            .to_string()
            .contains("tool_policy is required"));
        assert!(super::decode(Some(proto::ToolPolicy::default()))
            .unwrap_err()
            .to_string()
            .contains("default_decision"));
    }

    #[test]
    fn rejects_blank_selector() {
        let wire = proto::ToolPolicy {
            default_decision: proto::ToolDecision::Allow as i32,
            rules: vec![proto::ToolRule {
                decision: proto::ToolDecision::Ask as i32,
                selector: Some(proto::tool_rule::Selector::BuiltinName(" ".into())),
            }],
        };

        assert!(super::decode(Some(wire))
            .unwrap_err()
            .to_string()
            .contains("builtin tool name"));
    }
}
