use base64::Engine as _;
use envoy_types::pb::envoy::config::core::v3::Node;
use envoy_types::pb::google::protobuf::{value, Struct};
use sha2::{Digest, Sha256};
use thiserror::Error;

const LEGACY_SCHEMA_VERSION: &str = "v1";
const NODE_LOCAL_SCHEMA_VERSION: &str = "v2";

const REQUIRED_METADATA: [&str; 7] = [
    "deployment_id",
    "environment",
    "region",
    "provider",
    "shard_id",
    "envoy_version",
    "config_schema_version",
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GroupingMode {
    LegacyShared,
    NodeLocal,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeMetadata {
    pub deployment_id: String,
    pub environment: String,
    pub region: String,
    pub provider: String,
    pub shard_id: String,
    pub host_id: Option<String>,
    pub envoy_version: String,
    pub config_schema_version: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeIdentity {
    pub node_id: String,
    pub group_key: String,
    pub metadata: NodeMetadata,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum IdentityError {
    #[error("xDS node is required")]
    MissingNode,
    #[error("xDS node.id is required")]
    MissingNodeId,
    #[error("xDS node.metadata is required")]
    MissingMetadata,
    #[error("xDS node metadata {0:?} is required")]
    MissingMetadataField(String),
    #[error("node-local xDS metadata host_id is required")]
    MissingHostId,
    #[error("xDS node metadata contains control characters")]
    ControlCharacters,
}

impl NodeIdentity {
    pub fn from_node(node: Option<&Node>, mode: GroupingMode) -> Result<Self, IdentityError> {
        let node = node.ok_or(IdentityError::MissingNode)?;
        let node_id = normalize(&node.id);
        if node_id.is_empty() {
            return Err(IdentityError::MissingNodeId);
        }
        let metadata = NodeMetadata::from_struct(node.metadata.as_ref(), mode)?;
        let group_key = metadata.group_key(mode)?;
        Ok(Self {
            node_id,
            group_key,
            metadata,
        })
    }
}

impl NodeMetadata {
    fn from_struct(value: Option<&Struct>, mode: GroupingMode) -> Result<Self, IdentityError> {
        let value = value.ok_or(IdentityError::MissingMetadata)?;
        for name in REQUIRED_METADATA {
            if string_field(value, name).map_or(true, |field| normalize(field).is_empty()) {
                return Err(IdentityError::MissingMetadataField(name.to_string()));
            }
        }

        let host_id = string_field(value, "host_id")
            .map(normalize)
            .filter(|value| !value.is_empty());
        let provider = normalize(required_string_field(value, "provider")?);
        if mode == GroupingMode::NodeLocal && host_id.is_none() {
            return Err(IdentityError::MissingHostId);
        }
        if mode == GroupingMode::LegacyShared && provider == "docker" && host_id.is_none() {
            return Err(IdentityError::MissingHostId);
        }

        Ok(Self {
            deployment_id: normalize(required_string_field(value, "deployment_id")?),
            environment: normalize(required_string_field(value, "environment")?),
            region: normalize(required_string_field(value, "region")?),
            provider,
            shard_id: normalize(required_string_field(value, "shard_id")?),
            host_id,
            envoy_version: normalize(required_string_field(value, "envoy_version")?),
            config_schema_version: normalize(required_string_field(
                value,
                "config_schema_version",
            )?),
        })
    }

    pub fn group_key(&self, mode: GroupingMode) -> Result<String, IdentityError> {
        let mut values = vec![
            self.deployment_id.as_str(),
            self.environment.as_str(),
            self.region.as_str(),
            self.provider.as_str(),
            self.shard_id.as_str(),
        ];
        match mode {
            GroupingMode::LegacyShared if self.provider != "docker" => values.push(""),
            GroupingMode::LegacyShared | GroupingMode::NodeLocal => {
                values.push(self.host_id.as_deref().unwrap_or_default())
            }
        }
        values.extend([
            self.envoy_version.as_str(),
            self.config_schema_version.as_str(),
        ]);
        if values.iter().any(|value| {
            value
                .chars()
                .any(|character| matches!(character, '\0' | '\n' | '\r'))
        }) {
            return Err(IdentityError::ControlCharacters);
        }

        let canonical = values.join("\0");
        let digest = Sha256::digest(canonical.as_bytes());
        let encoded = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest);
        let schema = match mode {
            GroupingMode::LegacyShared => LEGACY_SCHEMA_VERSION,
            GroupingMode::NodeLocal => NODE_LOCAL_SCHEMA_VERSION,
        };
        Ok(format!("{schema}:{encoded}"))
    }
}

fn required_string_field<'a>(value: &'a Struct, name: &str) -> Result<&'a str, IdentityError> {
    string_field(value, name).ok_or_else(|| IdentityError::MissingMetadataField(name.to_string()))
}

fn string_field<'a>(value: &'a Struct, name: &str) -> Option<&'a str> {
    match value.fields.get(name)?.kind.as_ref()? {
        value::Kind::StringValue(value) => Some(value),
        _ => None,
    }
}

fn normalize(value: &str) -> String {
    value.trim().to_lowercase()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use envoy_types::pb::envoy::config::core::v3::Node;
    use envoy_types::pb::google::protobuf::{value, Struct, Value};

    use super::{GroupingMode, IdentityError, NodeIdentity};

    fn node(node_id: &str, provider: &str, host_id: Option<&str>) -> Node {
        let mut fields = HashMap::from([
            ("deployment_id".to_string(), string_value("Prod-A")),
            ("environment".to_string(), string_value("Production")),
            ("region".to_string(), string_value("cn-east-1")),
            ("provider".to_string(), string_value(provider)),
            ("shard_id".to_string(), string_value("17")),
            ("envoy_version".to_string(), string_value("1.39.0")),
            ("config_schema_version".to_string(), string_value("1")),
        ]);
        if let Some(host_id) = host_id {
            fields.insert("host_id".to_string(), string_value(host_id));
        }
        Node {
            id: node_id.to_string(),
            metadata: Some(Struct { fields }),
            ..Default::default()
        }
    }

    fn string_value(value: &str) -> Value {
        Value {
            kind: Some(value::Kind::StringValue(value.to_string())),
        }
    }

    #[test]
    fn legacy_shared_group_matches_nodes_with_same_metadata() {
        let first = NodeIdentity::from_node(
            Some(&node("envoy-a", "k8s", None)),
            GroupingMode::LegacyShared,
        )
        .expect("first identity");
        let second = NodeIdentity::from_node(
            Some(&node("envoy-b", "k8s", None)),
            GroupingMode::LegacyShared,
        )
        .expect("second identity");

        assert_eq!(first.group_key, second.group_key);
        assert_ne!(first.node_id, second.node_id);
        assert!(first.group_key.starts_with("v1:"));
    }

    #[test]
    fn node_local_group_isolated_by_host() {
        let first = NodeIdentity::from_node(
            Some(&node("envoy-a", "k8s", Some("node-a"))),
            GroupingMode::NodeLocal,
        )
        .expect("first identity");
        let second = NodeIdentity::from_node(
            Some(&node("envoy-b", "k8s", Some("node-b"))),
            GroupingMode::NodeLocal,
        )
        .expect("second identity");

        assert_ne!(first.group_key, second.group_key);
        assert!(first.group_key.starts_with("v2:"));
        assert!(second.group_key.starts_with("v2:"));
    }

    #[test]
    fn node_local_group_requires_host_identity() {
        let error =
            NodeIdentity::from_node(Some(&node("envoy-a", "k8s", None)), GroupingMode::NodeLocal)
                .expect_err("node-local identity must require host_id");

        assert_eq!(error, IdentityError::MissingHostId);
    }

    #[test]
    fn stream_identity_rejects_control_characters() {
        let error = NodeIdentity::from_node(
            Some(&node("envoy-a", "k8s", Some("node-a\nnode-b"))),
            GroupingMode::NodeLocal,
        )
        .expect_err("control characters must fail");

        assert_eq!(error, IdentityError::ControlCharacters);
    }
}
