use crate::ids::SandboxId;

const MAX_NODE_ID_BYTES: usize = 253;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SandboxPlacement {
    pub sandbox_id: SandboxId,
    pub node_id: String,
}

impl SandboxPlacement {
    pub fn new(sandbox_id: SandboxId, node_id: impl Into<String>) -> Result<Self, String> {
        let node_id = validated_node_id(node_id.into())?;
        Ok(Self {
            sandbox_id,
            node_id,
        })
    }
}

pub fn validated_node_id(value: String) -> Result<String, String> {
    let value = value.trim().to_string();
    if value.is_empty() || value.len() > MAX_NODE_ID_BYTES {
        return Err("node_id has an invalid length".to_string());
    }
    if !value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_' | b':'))
    {
        return Err("node_id contains unsupported characters".to_string());
    }
    Ok(value)
}

#[cfg(test)]
#[path = "../../tests/unit/domain/placement_test.rs"]
mod tests;
