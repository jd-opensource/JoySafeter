use crate::grpc::proto;
use crate::kernel::tool_policy::{ToolDecision, ToolPolicy, ToolRule, ToolSelector};

pub(crate) fn encode(policy: &ToolPolicy) -> proto::ToolPolicy {
    proto::ToolPolicy {
        default_decision: encode_decision(policy.default_decision()),
        rules: policy.rules().iter().map(encode_rule).collect(),
    }
}

fn encode_rule(rule: &ToolRule) -> proto::ToolRule {
    use proto::tool_rule::Selector;

    let selector = match &rule.selector {
        ToolSelector::Builtin { name } => Selector::BuiltinName(name.clone()),
        ToolSelector::Mcp { server, tool } => Selector::Mcp(proto::McpToolSelector {
            server_name: server.clone(),
            tool_name: tool.clone(),
        }),
    };
    proto::ToolRule {
        decision: encode_decision(rule.decision),
        selector: Some(selector),
    }
}

fn encode_decision(decision: ToolDecision) -> i32 {
    match decision {
        ToolDecision::Allow => proto::ToolDecision::Allow as i32,
        ToolDecision::Ask => proto::ToolDecision::Ask as i32,
        ToolDecision::Deny => proto::ToolDecision::Deny as i32,
    }
}

#[cfg(test)]
mod tests {
    use crate::kernel::tool_policy::{ToolDecision, ToolPolicy};

    #[test]
    fn maps_provider_neutral_policy_to_wire_contract() {
        let policy = ToolPolicy::from_agent_tools(Some(&serde_json::json!([
            {
                "type": "mcp_toolset",
                "mcp_server_name": "docs",
                "configs": [{"name": "search", "enabled": false}]
            }
        ])))
        .expect("valid policy");

        let wire = super::encode(&policy);

        assert_eq!(
            wire.default_decision,
            crate::grpc::proto::ToolDecision::Ask as i32
        );
        assert_eq!(wire.rules.len(), 2);
        assert_eq!(
            wire.rules[1].decision,
            crate::grpc::proto::ToolDecision::Deny as i32
        );
        assert!(matches!(
            wire.rules[1].selector,
            Some(crate::grpc::proto::tool_rule::Selector::Mcp(ref selector))
                if selector.server_name == "docs"
                    && selector.tool_name.as_deref() == Some("search")
        ));
        assert_eq!(policy.default_decision(), ToolDecision::Ask);
    }
}
