use std::collections::HashSet;
use std::sync::Arc;

use async_trait::async_trait;
use joysafeter_agent_gateway_contract::{
    AppliedSandboxGeneration, ApplySandboxPolicyRequest, CompleteRecoveryRequest, CredentialRoute,
    EgressExposure, EgressKind, PathMapping, PolicyGeneration, ResolvedHeader, RetryMode,
};
use tokio::sync::Mutex;

use crate::ids::SandboxId;
use crate::kernel::network_policy::envoy_model::{
    EgressCredentialRoute, EgressPathMapping, EgressPathMatcher, EgressRetryMode,
    SandboxEgressPolicy,
};
use crate::kernel::network_policy::ports::{
    NetworkPolicyApplyError, NetworkPolicyApplyRequest, NetworkPolicyRecoveryEntry,
    NetworkPolicyRecoveryFailure, NetworkPolicyRecoveryReport, NetworkPolicyRuntime,
};
use crate::sandbox::envoy::socket::EgressSocketProvisioner;

use super::{AgentGatewayApi, AgentGatewayResponseError};

pub struct AgentGatewayNetworkPolicyRuntime {
    client: Arc<dyn AgentGatewayApi>,
    sockets: Arc<EgressSocketProvisioner>,
    last_recovered_gateway: Mutex<Option<joysafeter_agent_gateway_contract::GatewayStatusResponse>>,
    event_publisher: Option<Arc<crate::grpc::policy_stream::RedisEventPublisher>>,
}

impl AgentGatewayNetworkPolicyRuntime {
    pub(crate) fn new(
        client: Arc<dyn AgentGatewayApi>,
        sockets: Arc<EgressSocketProvisioner>,
        event_publisher: Option<Arc<crate::grpc::policy_stream::RedisEventPublisher>>,
    ) -> Self {
        Self {
            client,
            sockets,
            last_recovered_gateway: Mutex::new(None),
            event_publisher,
        }
    }

    /// Publish the policy to the policy stream. Best-effort: a publish failure
    /// never fails the apply, since HTTP remains a fallback during migration.
    async fn publish_apply_event(
        &self,
        sandbox_id: SandboxId,
        request: &ApplySandboxPolicyRequest,
    ) {
        let Some(publisher) = &self.event_publisher else {
            return;
        };
        let payload = match serde_json::to_vec(request) {
            Ok(payload) => payload,
            Err(error) => {
                tracing::warn!(%sandbox_id, %error, "failed to serialize policy for stream");
                return;
            }
        };
        use crate::proto::policy_stream::{policy_event, ApplySandboxPolicy, PolicyEvent};
        let event = PolicyEvent {
            seq: 0,
            timestamp: None,
            trace_id: uuid::Uuid::now_v7().to_string(),
            event: Some(policy_event::Event::Apply(ApplySandboxPolicy {
                sandbox_id: sandbox_id.to_string(),
                generation: Some(crate::proto::policy_stream::PolicyGeneration {
                    policy_hash: request.generation.policy_hash.clone(),
                    policy_version: request.generation.policy_version as u64,
                }),
                policy_payload: payload,
                authority_epoch: 0,
            })),
        };
        if let Err(error) = publisher.publish_event(event).await {
            tracing::warn!(%sandbox_id, %error, "failed to publish policy event");
        }
    }

    async fn apply_policy(
        &self,
        sandbox_id: SandboxId,
        generation: crate::kernel::network_policy::NetworkPolicyGeneration,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        self.sockets.prepare_socket_dir(sandbox_id).await?;
        let request = into_request(generation, policy);
        // Dual-write to the policy stream (best-effort) alongside the HTTP call.
        self.publish_apply_event(sandbox_id, &request).await;
        if let Err(error) = self.client.apply_policy(sandbox_id, request).await {
            let is_nack = error.chain().any(|cause| {
                cause
                    .downcast_ref::<AgentGatewayResponseError>()
                    .is_some_and(|gateway| gateway.code() == "policy_nacked")
            });
            if is_nack {
                return Err(NetworkPolicyApplyError::Nacked(error).into());
            }
            return Err(error);
        }
        self.sockets.wait_for_socket_ready(sandbox_id).await
    }
}

#[async_trait]
impl NetworkPolicyRuntime for AgentGatewayNetworkPolicyRuntime {
    async fn initialize(&self) -> anyhow::Result<()> {
        self.client.check_ready().await
    }

    fn supports_ephemeral_credentials(&self) -> bool {
        true
    }

    async fn full_recovery_required(&self) -> anyhow::Result<bool> {
        let current = self.client.status().await?;
        Ok(self.last_recovered_gateway.lock().await.as_ref() != Some(&current))
    }

    async fn prune(&self, live_sandbox_ids: &HashSet<SandboxId>) -> anyhow::Result<usize> {
        let removed = self.client.prune_policies(live_sandbox_ids).await?;
        for sandbox_id in &removed {
            self.sockets.remove_socket_dir(*sandbox_id).await;
        }
        Ok(removed.len())
    }

    async fn recover(
        &self,
        _authority_epoch: u64,
        entries: Vec<NetworkPolicyRecoveryEntry>,
    ) -> anyhow::Result<NetworkPolicyRecoveryReport> {
        let gateway_before = self.client.status().await?;
        let current = gateway_before
            .generations
            .iter()
            .map(|entry| (entry.sandbox_id.as_str(), &entry.generation))
            .collect::<std::collections::HashMap<_, _>>();
        let mut report = NetworkPolicyRecoveryReport::default();
        let mut expected = Vec::with_capacity(entries.len());
        for entry in entries {
            let sandbox_id = entry.sandbox_id;
            let generation = entry.generation.clone();
            expected.push(AppliedSandboxGeneration {
                sandbox_id: sandbox_id.to_string(),
                generation: PolicyGeneration {
                    policy_hash: generation.policy_hash.clone(),
                    policy_version: generation.policy_version,
                },
            });
            if current
                .get(sandbox_id.to_string().as_str())
                .is_some_and(|applied| {
                    applied.policy_hash == generation.policy_hash
                        && applied.policy_version == generation.policy_version
                })
            {
                report.ready.push((sandbox_id, generation));
                continue;
            }
            match self
                .apply_policy(sandbox_id, generation.clone(), entry.policy)
                .await
            {
                Ok(()) => report.ready.push((sandbox_id, generation)),
                Err(error) => report.failed.push(NetworkPolicyRecoveryFailure {
                    sandbox_id,
                    generation,
                    reason: format!("Agent Gateway recovery delivery failed: {error:#}"),
                }),
            }
        }
        if report.failed.is_empty() && report.deferred.is_empty() {
            let live = expected
                .iter()
                .filter_map(|entry| entry.sandbox_id.parse().ok())
                .collect::<HashSet<_>>();
            self.client.prune_policies(&live).await?;
            expected.sort_by(|left, right| left.sandbox_id.cmp(&right.sandbox_id));
            self.client
                .complete_recovery(CompleteRecoveryRequest {
                    boot_id: gateway_before.boot_id.clone(),
                    authority_epoch: gateway_before.authority_epoch,
                    generations: expected,
                })
                .await?;
        }
        let gateway_after = self.client.status().await?;
        if gateway_before.boot_id == gateway_after.boot_id
            && gateway_before.authority_epoch == gateway_after.authority_epoch
            && report.failed.is_empty()
            && report.deferred.is_empty()
        {
            *self.last_recovered_gateway.lock().await = Some(gateway_after);
        }
        Ok(report)
    }

    async fn apply(
        &self,
        request: NetworkPolicyApplyRequest,
        policy: SandboxEgressPolicy,
    ) -> anyhow::Result<()> {
        self.apply_policy(request.sandbox_id, request.generation, policy)
            .await
    }

    async fn remove(
        &self,
        sandbox_id: SandboxId,
        generation: Option<&crate::kernel::network_policy::NetworkPolicyGeneration>,
    ) -> anyhow::Result<()> {
        if let Some(generation) = generation {
            self.client
                .remove_policy(
                    sandbox_id,
                    PolicyGeneration {
                        policy_hash: generation.policy_hash.clone(),
                        policy_version: generation.policy_version,
                    },
                )
                .await?;
        }
        self.sockets.remove_socket_dir(sandbox_id).await;
        Ok(())
    }
}

fn into_request(
    generation: crate::kernel::network_policy::NetworkPolicyGeneration,
    policy: SandboxEgressPolicy,
) -> ApplySandboxPolicyRequest {
    let contract_generation = PolicyGeneration {
        policy_hash: generation.policy_hash,
        policy_version: generation.policy_version,
    };
    ApplySandboxPolicyRequest {
        generation: contract_generation.clone(),
        allowlist_hosts: policy.allowlist_hosts,
        credential_routes: policy
            .credential_routes
            .into_iter()
            .map(into_credential_route)
            .collect(),
        proxy_auth_token: policy.proxy_auth_token,
    }
}

fn into_credential_route(route: EgressCredentialRoute) -> CredentialRoute {
    let inject_headers = route
        .inject_headers
        .into_iter()
        .map(|(name, value)| ResolvedHeader { name, value })
        .collect();
    CredentialRoute {
        id: route.id,
        kind: match route.kind {
            crate::kernel::network_policy::envoy_model::EgressKind::Llm => EgressKind::Llm,
            crate::kernel::network_policy::envoy_model::EgressKind::Mcp => EgressKind::Mcp,
            crate::kernel::network_policy::envoy_model::EgressKind::Git => EgressKind::Git,
            crate::kernel::network_policy::envoy_model::EgressKind::External => {
                EgressKind::External
            }
        },
        exposure: match route.exposure {
            crate::kernel::network_policy::envoy_model::EgressExposure::Placeholder => {
                EgressExposure::Placeholder
            }
            crate::kernel::network_policy::envoy_model::EgressExposure::Transparent => {
                EgressExposure::Transparent
            }
        },
        match_host: route.match_host,
        path_mapping: into_path_mapping(route.path_mapping),
        retry_mode: match route.retry_mode {
            EgressRetryMode::Disabled => RetryMode::Disabled,
            EgressRetryMode::SafeIdempotent => RetryMode::SafeIdempotent,
        },
        upstream_host: route.upstream_host,
        upstream_port: route.upstream_port,
        upstream_tls: route.upstream_tls,
        vetted_addresses: route.vetted_addresses,
        inject_headers,
        remove_headers: route.remove_headers,
    }
}

fn into_path_mapping(mapping: EgressPathMapping) -> PathMapping {
    match mapping {
        EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Any,
        } => PathMapping::PassthroughAny,
        EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Exact(path),
        } => PathMapping::PassthroughExact { path },
        EgressPathMapping::Passthrough {
            matcher: EgressPathMatcher::Prefix(path),
        } => PathMapping::PassthroughPrefix { path },
        EgressPathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        } => PathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        },
        EgressPathMapping::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        } => PathMapping::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        },
    }
}

#[cfg(test)]
#[path = "network_policy_test.rs"]
mod tests;
