use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ToolDecision {
    Allow,
    Ask,
    Deny,
}

impl ToolDecision {
    fn strictness(self) -> u8 {
        match self {
            Self::Allow => 0,
            Self::Ask => 1,
            Self::Deny => 2,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ToolSelector {
    Builtin {
        name: String,
    },
    Mcp {
        server: String,
        tool: Option<String>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ToolRule {
    pub selector: ToolSelector,
    pub decision: ToolDecision,
}

impl ToolRule {
    pub fn builtin(
        name: impl Into<String>,
        decision: ToolDecision,
    ) -> Result<Self, ToolPolicyError> {
        let name = required_component(name.into(), ToolPolicyError::BlankBuiltinName)?;
        Ok(Self {
            selector: ToolSelector::Builtin { name },
            decision,
        })
    }

    pub fn mcp_server(
        server: impl Into<String>,
        decision: ToolDecision,
    ) -> Result<Self, ToolPolicyError> {
        let server = required_component(server.into(), ToolPolicyError::BlankMcpServerName)?;
        Ok(Self {
            selector: ToolSelector::Mcp { server, tool: None },
            decision,
        })
    }

    pub fn mcp_tool(
        server: impl Into<String>,
        tool: impl Into<String>,
        decision: ToolDecision,
    ) -> Result<Self, ToolPolicyError> {
        let server = required_component(server.into(), ToolPolicyError::BlankMcpServerName)?;
        let tool = required_component(tool.into(), ToolPolicyError::BlankMcpToolName)?;
        Ok(Self {
            selector: ToolSelector::Mcp {
                server,
                tool: Some(tool),
            },
            decision,
        })
    }

    fn matching_specificity(&self, invocation: &ToolInvocation) -> Option<u8> {
        match (&self.selector, invocation) {
            (ToolSelector::Builtin { name }, ToolInvocation::Builtin { name: actual })
                if name == actual =>
            {
                Some(2)
            }
            (
                ToolSelector::Mcp { server, tool: None },
                ToolInvocation::Mcp {
                    server: actual_server,
                    ..
                },
            ) if server == actual_server => Some(1),
            (
                ToolSelector::Mcp {
                    server,
                    tool: Some(tool),
                },
                ToolInvocation::Mcp {
                    server: actual_server,
                    tool: actual_tool,
                },
            ) if server == actual_server && tool == actual_tool => Some(2),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolInvocation {
    Builtin { name: String },
    Mcp { server: String, tool: String },
}

impl ToolInvocation {
    pub fn builtin(name: impl Into<String>) -> Self {
        Self::Builtin { name: name.into() }
    }

    pub fn mcp(server: impl Into<String>, tool: impl Into<String>) -> Self {
        Self::Mcp {
            server: server.into(),
            tool: tool.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct ToolPolicy {
    default_decision: ToolDecision,
    rules: Vec<ToolRule>,
}

impl Default for ToolPolicy {
    fn default() -> Self {
        Self {
            default_decision: ToolDecision::Ask,
            rules: Vec::new(),
        }
    }
}

impl ToolPolicy {
    pub fn new(
        default_decision: ToolDecision,
        rules: Vec<ToolRule>,
    ) -> Result<Self, ToolPolicyError> {
        Ok(Self {
            default_decision,
            rules,
        })
    }

    pub fn default_decision(&self) -> ToolDecision {
        self.default_decision
    }

    pub fn rules(&self) -> &[ToolRule] {
        &self.rules
    }

    pub fn decision_for(&self, invocation: &ToolInvocation) -> ToolDecision {
        self.rules
            .iter()
            .filter_map(|rule| {
                rule.matching_specificity(invocation)
                    .map(|specificity| (specificity, rule.decision))
            })
            .max_by_key(|(specificity, decision)| (*specificity, decision.strictness()))
            .map(|(_, decision)| decision)
            .unwrap_or(self.default_decision)
    }

    pub fn is_unconditionally_allow(&self) -> bool {
        self.default_decision == ToolDecision::Allow
            && self
                .rules
                .iter()
                .all(|rule| rule.decision == ToolDecision::Allow)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
pub enum ToolPolicyError {
    #[error("builtin tool name must not be blank")]
    BlankBuiltinName,
    #[error("MCP server name must not be blank")]
    BlankMcpServerName,
    #[error("MCP tool name must not be blank")]
    BlankMcpToolName,
}

fn required_component(value: String, error: ToolPolicyError) -> Result<String, ToolPolicyError> {
    let value = value.trim();
    if value.is_empty() {
        Err(error)
    } else {
        Ok(value.to_string())
    }
}
