use std::collections::HashSet;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use envoy_types::pb::google::protobuf::Any;

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::{ClusterSpec, ListenerSpec};
use crate::sandbox::envoy_delivery::{CdsBackend, LdsBackend};
use crate::sandbox::envoy_render::{encode_cluster_any, encode_listener_any};

use super::control_plane::sandbox_id_from_resource_name;
use super::inventory::{InventoryMutation, XdsResource};
use super::model::ResourceType;
use super::transport::DeltaXdsServer;

pub struct GrpcLds {
    server: Arc<DeltaXdsServer>,
}

impl GrpcLds {
    pub fn new(server: Arc<DeltaXdsServer>) -> Self {
        Self { server }
    }
}

pub struct GrpcCds {
    server: Arc<DeltaXdsServer>,
}

impl GrpcCds {
    pub fn new(server: Arc<DeltaXdsServer>) -> Self {
        Self { server }
    }
}

#[async_trait]
impl LdsBackend for GrpcLds {
    async fn upsert(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut changes = Vec::with_capacity(specs.len());
        let mut pending_sandboxes = Vec::new();
        for spec in specs {
            if !pending_sandboxes.contains(&spec.sandbox_id) {
                pending_sandboxes.push(spec.sandbox_id);
            }
            changes.push(InventoryMutation::upsert(XdsResource::new(
                spec.sandbox_id,
                ResourceType::Listener,
                spec.resource_name(),
                domain_any(encode_listener_any(&spec)?),
            )));
        }
        self.server
            .apply(ResourceType::Listener, changes, pending_sandboxes)
            .await;
        Ok(())
    }

    async fn remove(&self, names: Vec<String>) -> anyhow::Result<()> {
        let changes = names
            .into_iter()
            .map(|name| {
                InventoryMutation::remove(
                    sandbox_id_from_resource_name(&name),
                    ResourceType::Listener,
                    name,
                )
            })
            .collect();
        self.server
            .apply(ResourceType::Listener, changes, vec![])
            .await;
        Ok(())
    }

    async fn replace_all(&self, specs: Vec<ListenerSpec>) -> anyhow::Result<()> {
        let mut new_names = HashSet::new();
        let mut changes = Vec::new();
        let mut pending_sandboxes = Vec::new();
        for spec in &specs {
            let name = spec.resource_name();
            new_names.insert(name.clone());
            if !pending_sandboxes.contains(&spec.sandbox_id) {
                pending_sandboxes.push(spec.sandbox_id);
            }
            changes.push(InventoryMutation::upsert(XdsResource::new(
                spec.sandbox_id,
                ResourceType::Listener,
                name,
                domain_any(encode_listener_any(spec)?),
            )));
        }
        for existing in self.server.resource_names(ResourceType::Listener) {
            if !new_names.contains(&existing) {
                changes.push(InventoryMutation::remove(
                    sandbox_id_from_resource_name(&existing),
                    ResourceType::Listener,
                    existing,
                ));
            }
        }
        self.server
            .apply(ResourceType::Listener, changes, pending_sandboxes)
            .await;
        Ok(())
    }

    async fn configured_sandbox_ids(&self) -> HashSet<SandboxId> {
        self.server.configured_sandbox_ids()
    }

    async fn wait_for_sandbox_ack(
        &self,
        sandbox_id: SandboxId,
        timeout: Duration,
    ) -> anyhow::Result<()> {
        self.server.wait_for_sandbox_ack(sandbox_id, timeout).await
    }

    async fn forget_sandbox(&self, sandbox_id: SandboxId) {
        self.server.forget_sandbox(sandbox_id).await;
    }

    async fn apply_sandbox_batch(
        &self,
        clusters: Vec<ClusterSpec>,
        listeners: Vec<ListenerSpec>,
        cluster_prefix: String,
    ) -> anyhow::Result<bool> {
        let mut new_cluster_names = HashSet::new();
        let mut cluster_changes = Vec::with_capacity(clusters.len());
        for spec in &clusters {
            new_cluster_names.insert(spec.name.clone());
            cluster_changes.push(InventoryMutation::upsert(resource(
                ResourceType::Cluster,
                spec.name.clone(),
                encode_cluster_any(spec)?,
            )));
        }
        for existing in self
            .server
            .resource_names_with_prefix(ResourceType::Cluster, &cluster_prefix)
        {
            if !new_cluster_names.contains(&existing) {
                cluster_changes.push(InventoryMutation::remove(
                    sandbox_id_from_resource_name(&existing),
                    ResourceType::Cluster,
                    existing,
                ));
            }
        }

        let mut listener_changes = Vec::with_capacity(listeners.len());
        let mut pending_sandboxes = Vec::new();
        for spec in &listeners {
            if !pending_sandboxes.contains(&spec.sandbox_id) {
                pending_sandboxes.push(spec.sandbox_id);
            }
            listener_changes.push(InventoryMutation::upsert(XdsResource::new(
                spec.sandbox_id,
                ResourceType::Listener,
                spec.resource_name(),
                domain_any(encode_listener_any(spec)?),
            )));
        }
        self.server
            .apply_batch(
                vec![
                    (ResourceType::Cluster, cluster_changes),
                    (ResourceType::Listener, listener_changes),
                ],
                pending_sandboxes,
            )
            .await;
        Ok(true)
    }
}

#[async_trait]
impl CdsBackend for GrpcCds {
    async fn upsert(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut changes = Vec::with_capacity(specs.len());
        for spec in specs {
            changes.push(InventoryMutation::upsert(resource(
                ResourceType::Cluster,
                spec.name.clone(),
                encode_cluster_any(&spec)?,
            )));
        }
        self.server
            .apply(ResourceType::Cluster, changes, vec![])
            .await;
        Ok(())
    }

    async fn remove_by_prefix(&self, prefix: &str) -> anyhow::Result<()> {
        let changes = self
            .server
            .resource_names_with_prefix(ResourceType::Cluster, prefix)
            .into_iter()
            .map(|name| {
                InventoryMutation::remove(
                    sandbox_id_from_resource_name(&name),
                    ResourceType::Cluster,
                    name,
                )
            })
            .collect();
        self.server
            .apply(ResourceType::Cluster, changes, vec![])
            .await;
        Ok(())
    }

    async fn replace_by_prefix(&self, prefix: &str, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut new_names = HashSet::new();
        let mut changes = Vec::new();
        for spec in &specs {
            new_names.insert(spec.name.clone());
            changes.push(InventoryMutation::upsert(resource(
                ResourceType::Cluster,
                spec.name.clone(),
                encode_cluster_any(spec)?,
            )));
        }
        for existing in self
            .server
            .resource_names_with_prefix(ResourceType::Cluster, prefix)
        {
            if !new_names.contains(&existing) {
                changes.push(InventoryMutation::remove(
                    sandbox_id_from_resource_name(&existing),
                    ResourceType::Cluster,
                    existing,
                ));
            }
        }
        self.server
            .apply(ResourceType::Cluster, changes, vec![])
            .await;
        Ok(())
    }

    async fn replace_all(&self, specs: Vec<ClusterSpec>) -> anyhow::Result<()> {
        let mut new_names = HashSet::new();
        let mut changes = Vec::new();
        for spec in &specs {
            new_names.insert(spec.name.clone());
            changes.push(InventoryMutation::upsert(resource(
                ResourceType::Cluster,
                spec.name.clone(),
                encode_cluster_any(spec)?,
            )));
        }
        for existing in self.server.resource_names(ResourceType::Cluster) {
            if !new_names.contains(&existing) {
                changes.push(InventoryMutation::remove(
                    sandbox_id_from_resource_name(&existing),
                    ResourceType::Cluster,
                    existing,
                ));
            }
        }
        self.server
            .apply(ResourceType::Cluster, changes, vec![])
            .await;
        Ok(())
    }
}

fn resource(resource_type: ResourceType, name: String, payload: Any) -> XdsResource {
    let payload = domain_any(payload);
    match sandbox_id_from_resource_name(&name) {
        Some(sandbox_id) => XdsResource::new(sandbox_id, resource_type, name, payload),
        None => XdsResource::shared(resource_type, name, payload),
    }
}

fn domain_any(payload: Any) -> prost_types::Any {
    prost_types::Any {
        type_url: payload.type_url,
        value: payload.value,
    }
}
