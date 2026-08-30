use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolDecision {
    Allow,
    Ask,
    Deny,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ToolSelector {
    Builtin {
        name: String,
    },
    Mcp {
        server: String,
        tool: Option<String>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolRule {
    pub selector: ToolSelector,
    pub decision: ToolDecision,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ToolPolicy {
    default_decision: ToolDecision,
    rules: Vec<ToolRule>,
}

impl Default for ToolPolicy {
    fn default() -> Self {
        Self::fail_closed()
    }
}

impl ToolPolicy {
    pub fn from_agent_tools(tools: Option<&Value>) -> Result<Self, ToolPolicyError> {
        let Some(tools) = tools else {
            return Ok(Self::fail_closed());
        };
        let items = tools.as_array().ok_or(ToolPolicyError::InvalidToolsShape)?;
        let mut default_decision = ToolDecision::Ask;
        let mut has_builtin_toolset = false;
        let mut rules = Vec::new();

        for item in items {
            let item = item.as_object().ok_or(ToolPolicyError::InvalidToolShape)?;
            let tool_type = required_string(item.get("type"), "type")?;
            match tool_type.as_str() {
                "agent_toolset_20260401" => {
                    if has_builtin_toolset {
                        return Err(ToolPolicyError::DuplicateBuiltinToolset);
                    }
                    has_builtin_toolset = true;
                    default_decision = configured_decision(item.get("default_config"))?
                        .unwrap_or(ToolDecision::Allow);
                    parse_builtin_rules(item.get("configs"), default_decision, &mut rules)?;
                }
                "mcp_toolset" => {
                    let server = required_string(item.get("mcp_server_name"), "mcp_server_name")?;
                    let server_decision = configured_decision(item.get("default_config"))?
                        .unwrap_or(ToolDecision::Ask);
                    rules.push(ToolRule {
                        selector: ToolSelector::Mcp {
                            server: server.clone(),
                            tool: None,
                        },
                        decision: server_decision,
                    });
                    parse_mcp_rules(item.get("configs"), &server, server_decision, &mut rules)?;
                }
                "custom" => {}
                unsupported => {
                    return Err(ToolPolicyError::UnsupportedToolType(
                        unsupported.to_string(),
                    ));
                }
            }
        }

        Ok(Self {
            default_decision,
            rules,
        })
    }

    pub fn fail_closed() -> Self {
        Self {
            default_decision: ToolDecision::Ask,
            rules: Vec::new(),
        }
    }

    pub fn default_decision(&self) -> ToolDecision {
        self.default_decision
    }

    pub fn rules(&self) -> &[ToolRule] {
        &self.rules
    }
}

fn parse_builtin_rules(
    configs: Option<&Value>,
    default_decision: ToolDecision,
    rules: &mut Vec<ToolRule>,
) -> Result<(), ToolPolicyError> {
    for config in optional_configs(configs)? {
        let name = required_string(config.get("name"), "configs[].name")?;
        rules.push(ToolRule {
            selector: ToolSelector::Builtin { name },
            decision: config_decision(config, default_decision)?,
        });
    }
    Ok(())
}

fn parse_mcp_rules(
    configs: Option<&Value>,
    server: &str,
    default_decision: ToolDecision,
    rules: &mut Vec<ToolRule>,
) -> Result<(), ToolPolicyError> {
    for config in optional_configs(configs)? {
        let tool = required_string(config.get("name"), "configs[].name")?;
        rules.push(ToolRule {
            selector: ToolSelector::Mcp {
                server: server.to_string(),
                tool: Some(tool),
            },
            decision: config_decision(config, default_decision)?,
        });
    }
    Ok(())
}

fn optional_configs(
    value: Option<&Value>,
) -> Result<Vec<&serde_json::Map<String, Value>>, ToolPolicyError> {
    let Some(value) = value else {
        return Ok(Vec::new());
    };
    value
        .as_array()
        .ok_or(ToolPolicyError::InvalidConfigsShape)?
        .iter()
        .map(|config| {
            config
                .as_object()
                .ok_or(ToolPolicyError::InvalidConfigShape)
        })
        .collect()
}

fn config_decision(
    config: &serde_json::Map<String, Value>,
    inherited: ToolDecision,
) -> Result<ToolDecision, ToolPolicyError> {
    match config.get("enabled") {
        Some(Value::Bool(false)) => return Ok(ToolDecision::Deny),
        Some(Value::Bool(true)) | None => {}
        Some(_) => return Err(ToolPolicyError::InvalidEnabledFlag),
    }
    Ok(optional_permission_policy(config.get("permission_policy"))?.unwrap_or(inherited))
}

fn configured_decision(value: Option<&Value>) -> Result<Option<ToolDecision>, ToolPolicyError> {
    let Some(value) = value else {
        return Ok(None);
    };
    let object = value
        .as_object()
        .ok_or(ToolPolicyError::InvalidPermissionPolicyShape)?;
    optional_permission_policy(object.get("permission_policy"))
}

fn optional_permission_policy(
    value: Option<&Value>,
) -> Result<Option<ToolDecision>, ToolPolicyError> {
    value.map(parse_permission_policy).transpose()
}

fn parse_permission_policy(value: &Value) -> Result<ToolDecision, ToolPolicyError> {
    let object = value
        .as_object()
        .ok_or(ToolPolicyError::InvalidPermissionPolicyShape)?;
    match required_string(object.get("type"), "permission_policy.type")?.as_str() {
        "always_allow" => Ok(ToolDecision::Allow),
        "always_ask" => Ok(ToolDecision::Ask),
        unsupported => Err(ToolPolicyError::UnsupportedDecision(
            unsupported.to_string(),
        )),
    }
}

fn required_string(value: Option<&Value>, field: &'static str) -> Result<String, ToolPolicyError> {
    let value = value
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or(ToolPolicyError::MissingRequiredField(field))?;
    Ok(value.to_string())
}

#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum ToolPolicyError {
    #[error("agent tools must be an array")]
    InvalidToolsShape,
    #[error("agent tool must be an object")]
    InvalidToolShape,
    #[error("tool configs must be an array")]
    InvalidConfigsShape,
    #[error("tool config must be an object")]
    InvalidConfigShape,
    #[error("tool enabled flag must be boolean")]
    InvalidEnabledFlag,
    #[error("permission policy must be an object")]
    InvalidPermissionPolicyShape,
    #[error("missing required tool field {0}")]
    MissingRequiredField(&'static str),
    #[error("unsupported tool type {0}")]
    UnsupportedToolType(String),
    #[error("unsupported tool decision {0}")]
    UnsupportedDecision(String),
    #[error("only one built-in toolset is allowed")]
    DuplicateBuiltinToolset,
}
