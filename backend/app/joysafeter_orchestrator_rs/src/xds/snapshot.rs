use std::collections::BTreeMap;

use envoy_types::pb::google::protobuf::Any;

pub const CLUSTER_TYPE_URL: &str = "type.googleapis.com/envoy.config.cluster.v3.Cluster";
pub const ROUTE_TYPE_URL: &str = "type.googleapis.com/envoy.config.route.v3.RouteConfiguration";
pub const LISTENER_TYPE_URL: &str = "type.googleapis.com/envoy.config.listener.v3.Listener";

#[derive(Debug, Clone, PartialEq)]
pub struct CompiledSnapshot {
    pub group_key: String,
    pub generation: i64,
    pub version: String,
    pub resources: BTreeMap<String, BTreeMap<String, Any>>,
}

impl CompiledSnapshot {
    pub fn new(
        group_key: impl Into<String>,
        generation: i64,
        content_sha256: &str,
        resources: BTreeMap<String, BTreeMap<String, Any>>,
    ) -> anyhow::Result<Self> {
        let group_key = group_key.into();
        anyhow::ensure!(
            !group_key.trim().is_empty(),
            "xDS snapshot group key is required"
        );
        anyhow::ensure!(generation > 0, "xDS snapshot generation must be positive");
        let digest = content_sha256.trim().to_ascii_lowercase();
        anyhow::ensure!(
            digest.len() == 64 && digest.bytes().all(|value| value.is_ascii_hexdigit()),
            "xDS snapshot content_sha256 must be 64 hexadecimal characters"
        );
        for (type_url, typed_resources) in &resources {
            anyhow::ensure!(
                !type_url.trim().is_empty(),
                "xDS resource type URL is required"
            );
            anyhow::ensure!(
                matches!(
                    type_url.as_str(),
                    CLUSTER_TYPE_URL | ROUTE_TYPE_URL | LISTENER_TYPE_URL
                ),
                "unsupported xDS resource type {type_url}"
            );
            anyhow::ensure!(
                typed_resources.keys().all(|name| !name.trim().is_empty()),
                "xDS resource names must be non-empty"
            );
        }
        let version = format!("g{generation}-{}", &digest[..32]);
        Ok(Self {
            group_key,
            generation,
            version,
            resources,
        })
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::CompiledSnapshot;

    #[test]
    fn deterministic_version_uses_generation_and_durable_content_hash() {
        let digest = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";
        let first = CompiledSnapshot::new("v2:node-a", 42, digest, BTreeMap::new()).unwrap();
        let second = CompiledSnapshot::new("v2:node-a", 42, digest, BTreeMap::new()).unwrap();
        assert_eq!(first.version, "g42-0123456789abcdef0123456789abcdef");
        assert_eq!(first.version, second.version);
    }

    #[test]
    fn snapshot_rejects_invalid_durable_identity() {
        assert!(CompiledSnapshot::new("", 1, &"0".repeat(64), BTreeMap::new()).is_err());
        assert!(CompiledSnapshot::new("v2:node", 0, &"0".repeat(64), BTreeMap::new()).is_err());
        assert!(CompiledSnapshot::new("v2:node", 1, "not-a-sha", BTreeMap::new()).is_err());
    }
}
