use joysafeter_agent_gateway_contract as contract;

use crate::proto::gateway_management as proto;
use crate::replication::model::{
    ReplicaEvent, ReplicaEventPayload, ReplicaMutation, ReplicatedPolicy, ReplicatedSnapshot,
};

pub(crate) fn policy_from_proto(
    policy: proto::SandboxPolicy,
) -> anyhow::Result<contract::ApplySandboxPolicyRequest> {
    Ok(contract::ApplySandboxPolicyRequest {
        generation: generation_from_proto(
            policy
                .generation
                .ok_or_else(|| anyhow::anyhow!("policy generation is required"))?,
        )?,
        allowlist_hosts: policy.allowlist_hosts,
        credential_routes: policy
            .credential_routes
            .into_iter()
            .map(route_from_proto)
            .collect::<anyhow::Result<_>>()?,
        proxy_auth_token: policy.proxy_auth_token,
    })
}

pub(crate) fn policy_to_proto(
    policy: contract::ApplySandboxPolicyRequest,
) -> anyhow::Result<proto::SandboxPolicy> {
    Ok(proto::SandboxPolicy {
        generation: Some(generation_to_proto(policy.generation)?),
        allowlist_hosts: policy.allowlist_hosts,
        credential_routes: policy
            .credential_routes
            .into_iter()
            .map(route_to_proto)
            .collect::<anyhow::Result<_>>()?,
        proxy_auth_token: policy.proxy_auth_token,
    })
}

pub(crate) fn generation_from_proto(
    generation: proto::PolicyGeneration,
) -> anyhow::Result<contract::PolicyGeneration> {
    let policy_version = i64::try_from(generation.policy_version)
        .map_err(|_| anyhow::anyhow!("policy version exceeds the supported range"))?;
    if policy_version <= 0 || generation.policy_hash.is_empty() {
        anyhow::bail!("policy generation is invalid");
    }
    Ok(contract::PolicyGeneration {
        policy_hash: generation.policy_hash,
        policy_version,
    })
}

pub(crate) fn generation_to_proto(
    generation: contract::PolicyGeneration,
) -> anyhow::Result<proto::PolicyGeneration> {
    let policy_version = u64::try_from(generation.policy_version)
        .map_err(|_| anyhow::anyhow!("policy version must be positive"))?;
    if policy_version == 0 {
        anyhow::bail!("policy version must be positive");
    }
    Ok(proto::PolicyGeneration {
        policy_hash: generation.policy_hash,
        policy_version,
    })
}

fn route_from_proto(route: proto::CredentialRoute) -> anyhow::Result<contract::CredentialRoute> {
    let kind = match proto::EgressKind::try_from(route.kind) {
        Ok(proto::EgressKind::Llm) => contract::EgressKind::Llm,
        Ok(proto::EgressKind::Mcp) => contract::EgressKind::Mcp,
        Ok(proto::EgressKind::Git) => contract::EgressKind::Git,
        Ok(proto::EgressKind::External) => contract::EgressKind::External,
        _ => anyhow::bail!("egress kind is invalid"),
    };
    let exposure = match proto::EgressExposure::try_from(route.exposure) {
        Ok(proto::EgressExposure::Placeholder) => contract::EgressExposure::Placeholder,
        Ok(proto::EgressExposure::Transparent) => contract::EgressExposure::Transparent,
        _ => anyhow::bail!("egress exposure is invalid"),
    };
    let retry_mode = match proto::RetryMode::try_from(route.retry_mode) {
        Ok(proto::RetryMode::Disabled) => contract::RetryMode::Disabled,
        Ok(proto::RetryMode::SafeIdempotent) => contract::RetryMode::SafeIdempotent,
        _ => anyhow::bail!("retry mode is invalid"),
    };
    let upstream_port = u16::try_from(route.upstream_port)
        .map_err(|_| anyhow::anyhow!("upstream port exceeds the supported range"))?;
    Ok(contract::CredentialRoute {
        id: route.id,
        kind,
        exposure,
        match_host: route.match_host,
        path_mapping: path_mapping_from_proto(
            route
                .path_mapping
                .ok_or_else(|| anyhow::anyhow!("path mapping is required"))?,
        )?,
        retry_mode,
        upstream_host: route.upstream_host,
        upstream_port,
        upstream_tls: route.upstream_tls,
        vetted_addresses: route.vetted_addresses,
        inject_headers: route
            .inject_headers
            .into_iter()
            .map(|header| contract::ResolvedHeader {
                name: header.name,
                value: header.value,
            })
            .collect(),
        remove_headers: route.remove_headers,
    })
}

fn route_to_proto(route: contract::CredentialRoute) -> anyhow::Result<proto::CredentialRoute> {
    Ok(proto::CredentialRoute {
        id: route.id,
        kind: match route.kind {
            contract::EgressKind::Llm => proto::EgressKind::Llm as i32,
            contract::EgressKind::Mcp => proto::EgressKind::Mcp as i32,
            contract::EgressKind::Git => proto::EgressKind::Git as i32,
            contract::EgressKind::External => proto::EgressKind::External as i32,
        },
        exposure: match route.exposure {
            contract::EgressExposure::Placeholder => proto::EgressExposure::Placeholder as i32,
            contract::EgressExposure::Transparent => proto::EgressExposure::Transparent as i32,
        },
        match_host: route.match_host,
        path_mapping: Some(path_mapping_to_proto(route.path_mapping)),
        retry_mode: match route.retry_mode {
            contract::RetryMode::Disabled => proto::RetryMode::Disabled as i32,
            contract::RetryMode::SafeIdempotent => proto::RetryMode::SafeIdempotent as i32,
        },
        upstream_host: route.upstream_host,
        upstream_port: u32::from(route.upstream_port),
        upstream_tls: route.upstream_tls,
        vetted_addresses: route.vetted_addresses,
        inject_headers: route
            .inject_headers
            .into_iter()
            .map(|header| proto::ResolvedHeader {
                name: header.name,
                value: header.value,
            })
            .collect(),
        remove_headers: route.remove_headers,
    })
}

fn path_mapping_from_proto(mapping: proto::PathMapping) -> anyhow::Result<contract::PathMapping> {
    use proto::path_mapping::Mapping;
    Ok(
        match mapping
            .mapping
            .ok_or_else(|| anyhow::anyhow!("path mapping variant is required"))?
        {
            Mapping::PassthroughAny(_) => contract::PathMapping::PassthroughAny,
            Mapping::PassthroughExact(path) => contract::PathMapping::PassthroughExact { path },
            Mapping::PassthroughPrefix(path) => contract::PathMapping::PassthroughPrefix { path },
            Mapping::RewriteExact(mapping) => contract::PathMapping::RewriteExact {
                exposed_path: mapping.exposed_path,
                upstream_path: mapping.upstream_path,
            },
            Mapping::RewritePrefix(mapping) => contract::PathMapping::RewritePrefix {
                exposed_prefix: mapping.exposed_prefix,
                upstream_prefix: mapping.upstream_prefix,
            },
        },
    )
}

fn path_mapping_to_proto(mapping: contract::PathMapping) -> proto::PathMapping {
    use proto::path_mapping::Mapping;
    let mapping = match mapping {
        contract::PathMapping::PassthroughAny => Mapping::PassthroughAny(proto::Empty {}),
        contract::PathMapping::PassthroughExact { path } => Mapping::PassthroughExact(path),
        contract::PathMapping::PassthroughPrefix { path } => Mapping::PassthroughPrefix(path),
        contract::PathMapping::RewriteExact {
            exposed_path,
            upstream_path,
        } => Mapping::RewriteExact(proto::RewriteExact {
            exposed_path,
            upstream_path,
        }),
        contract::PathMapping::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        } => Mapping::RewritePrefix(proto::RewritePrefix {
            exposed_prefix,
            upstream_prefix,
        }),
    };
    proto::PathMapping {
        mapping: Some(mapping),
    }
}

pub(crate) fn replica_event_to_proto(event: ReplicaEvent) -> anyhow::Result<proto::ReplicaEvent> {
    use proto::replica_event::Payload;
    let payload = match event.payload {
        ReplicaEventPayload::SnapshotBegin { chunk_count } => {
            Payload::SnapshotBegin(proto::ReplicaSnapshotBegin {
                chunk_count: u64::try_from(chunk_count)?,
            })
        }
        ReplicaEventPayload::SnapshotChunk {
            chunk_index,
            snapshot,
        } => Payload::SnapshotChunk(proto::ReplicaSnapshotChunk {
            chunk_index: u64::try_from(chunk_index)?,
            snapshot: Some(snapshot_to_proto(snapshot)?),
        }),
        ReplicaEventPayload::SnapshotEnd => Payload::SnapshotEnd(proto::Empty {}),
        ReplicaEventPayload::Delta { mutation } => Payload::Delta(mutation_to_proto(mutation)?),
    };
    Ok(proto::ReplicaEvent {
        protocol_version: u32::from(event.protocol_version),
        source_instance: event.source_instance,
        term: event.term,
        revision: event.revision,
        snapshot_digest: event.snapshot_digest,
        payload: Some(payload),
    })
}

pub(crate) fn replica_event_from_proto(event: proto::ReplicaEvent) -> anyhow::Result<ReplicaEvent> {
    use proto::replica_event::Payload;
    let payload = match event
        .payload
        .ok_or_else(|| anyhow::anyhow!("replica event payload is required"))?
    {
        Payload::SnapshotBegin(begin) => ReplicaEventPayload::SnapshotBegin {
            chunk_count: usize::try_from(begin.chunk_count)?,
        },
        Payload::SnapshotChunk(chunk) => ReplicaEventPayload::SnapshotChunk {
            chunk_index: usize::try_from(chunk.chunk_index)?,
            snapshot: snapshot_from_proto(
                chunk
                    .snapshot
                    .ok_or_else(|| anyhow::anyhow!("replica snapshot chunk is required"))?,
            )?,
        },
        Payload::SnapshotEnd(_) => ReplicaEventPayload::SnapshotEnd,
        Payload::Delta(mutation) => ReplicaEventPayload::Delta {
            mutation: mutation_from_proto(mutation)?,
        },
    };
    Ok(ReplicaEvent {
        protocol_version: u16::try_from(event.protocol_version)?,
        source_instance: event.source_instance,
        term: event.term,
        revision: event.revision,
        snapshot_digest: event.snapshot_digest,
        payload,
    })
}

fn snapshot_to_proto(snapshot: ReplicatedSnapshot) -> anyhow::Result<proto::ReplicatedSnapshot> {
    Ok(proto::ReplicatedSnapshot {
        policies: snapshot
            .policies
            .into_iter()
            .map(replicated_policy_to_proto)
            .collect::<anyhow::Result<_>>()?,
        placements: snapshot
            .placements
            .into_iter()
            .map(placement_to_proto)
            .collect(),
    })
}

fn snapshot_from_proto(snapshot: proto::ReplicatedSnapshot) -> anyhow::Result<ReplicatedSnapshot> {
    Ok(ReplicatedSnapshot {
        policies: snapshot
            .policies
            .into_iter()
            .map(replicated_policy_from_proto)
            .collect::<anyhow::Result<_>>()?,
        placements: snapshot
            .placements
            .into_iter()
            .map(placement_from_proto)
            .collect(),
    })
}

fn replicated_policy_to_proto(policy: ReplicatedPolicy) -> anyhow::Result<proto::ReplicatedPolicy> {
    Ok(proto::ReplicatedPolicy {
        sandbox_id: policy.sandbox_id,
        policy: Some(policy_to_proto(policy.policy)?),
    })
}

fn replicated_policy_from_proto(
    policy: proto::ReplicatedPolicy,
) -> anyhow::Result<ReplicatedPolicy> {
    Ok(ReplicatedPolicy {
        sandbox_id: policy.sandbox_id,
        policy: policy_from_proto(
            policy
                .policy
                .ok_or_else(|| anyhow::anyhow!("replicated policy is required"))?,
        )?,
    })
}

fn placement_to_proto(placement: contract::SandboxPlacement) -> proto::ReplicaSandboxPlacement {
    proto::ReplicaSandboxPlacement {
        sandbox_id: placement.sandbox_id,
        node_id: placement.node_id,
    }
}

fn placement_from_proto(placement: proto::ReplicaSandboxPlacement) -> contract::SandboxPlacement {
    contract::SandboxPlacement {
        sandbox_id: placement.sandbox_id,
        node_id: placement.node_id,
    }
}

fn mutation_to_proto(mutation: ReplicaMutation) -> anyhow::Result<proto::ReplicaMutation> {
    use proto::replica_mutation::Mutation;
    let mutation = match mutation {
        ReplicaMutation::UpsertPolicy { policy } => {
            Mutation::UpsertPolicy(replicated_policy_to_proto(policy)?)
        }
        ReplicaMutation::RemovePolicy { sandbox_id } => Mutation::RemovePolicySandboxId(sandbox_id),
        ReplicaMutation::UpsertPlacement { placement } => {
            Mutation::UpsertPlacement(placement_to_proto(placement))
        }
        ReplicaMutation::RemovePlacement { sandbox_id } => {
            Mutation::RemovePlacementSandboxId(sandbox_id)
        }
        ReplicaMutation::ReplacePlacements { placements } => {
            Mutation::ReplacePlacements(proto::ReplicaPlacementSet {
                placements: placements.into_iter().map(placement_to_proto).collect(),
            })
        }
    };
    Ok(proto::ReplicaMutation {
        mutation: Some(mutation),
    })
}

fn mutation_from_proto(mutation: proto::ReplicaMutation) -> anyhow::Result<ReplicaMutation> {
    use proto::replica_mutation::Mutation;
    Ok(
        match mutation
            .mutation
            .ok_or_else(|| anyhow::anyhow!("replica mutation is required"))?
        {
            Mutation::UpsertPolicy(policy) => ReplicaMutation::UpsertPolicy {
                policy: replicated_policy_from_proto(policy)?,
            },
            Mutation::RemovePolicySandboxId(sandbox_id) => {
                ReplicaMutation::RemovePolicy { sandbox_id }
            }
            Mutation::UpsertPlacement(placement) => ReplicaMutation::UpsertPlacement {
                placement: placement_from_proto(placement),
            },
            Mutation::RemovePlacementSandboxId(sandbox_id) => {
                ReplicaMutation::RemovePlacement { sandbox_id }
            }
            Mutation::ReplacePlacements(placements) => ReplicaMutation::ReplacePlacements {
                placements: placements
                    .placements
                    .into_iter()
                    .map(placement_from_proto)
                    .collect(),
            },
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_policy() -> contract::ApplySandboxPolicyRequest {
        let mappings = [
            contract::PathMapping::PassthroughAny,
            contract::PathMapping::PassthroughExact {
                path: "/v1/chat".to_string(),
            },
            contract::PathMapping::PassthroughPrefix {
                path: "/mcp/".to_string(),
            },
            contract::PathMapping::RewriteExact {
                exposed_path: "/token".to_string(),
                upstream_path: "/v2/token".to_string(),
            },
            contract::PathMapping::RewritePrefix {
                exposed_prefix: "/git/".to_string(),
                upstream_prefix: "/api/git/".to_string(),
            },
        ];
        let kinds = [
            contract::EgressKind::Llm,
            contract::EgressKind::Mcp,
            contract::EgressKind::Git,
            contract::EgressKind::External,
            contract::EgressKind::Mcp,
        ];
        contract::ApplySandboxPolicyRequest {
            generation: contract::PolicyGeneration {
                policy_hash: "a".repeat(64),
                policy_version: 7,
            },
            allowlist_hosts: vec!["api.example.test".to_string()],
            credential_routes: mappings
                .into_iter()
                .zip(kinds)
                .enumerate()
                .map(|(index, (path_mapping, kind))| contract::CredentialRoute {
                    id: format!("route-{index}"),
                    kind,
                    exposure: if index % 2 == 0 {
                        contract::EgressExposure::Placeholder
                    } else {
                        contract::EgressExposure::Transparent
                    },
                    match_host: "api.example.test".to_string(),
                    path_mapping,
                    retry_mode: if index % 2 == 0 {
                        contract::RetryMode::Disabled
                    } else {
                        contract::RetryMode::SafeIdempotent
                    },
                    upstream_host: "upstream.example.test".to_string(),
                    upstream_port: 8443,
                    upstream_tls: true,
                    vetted_addresses: vec!["192.0.2.10".to_string()],
                    inject_headers: vec![contract::ResolvedHeader {
                        name: "authorization".to_string(),
                        value: "Bearer secret".to_string(),
                    }],
                    remove_headers: vec!["x-untrusted".to_string()],
                })
                .collect(),
            proxy_auth_token: Some("proxy-secret".to_string()),
        }
    }

    fn assert_json_equal<T: serde::Serialize, U: serde::Serialize>(left: &T, right: &U) {
        assert_eq!(
            serde_json::to_value(left).expect("serialize left"),
            serde_json::to_value(right).expect("serialize right")
        );
    }

    #[test]
    fn strongly_typed_policy_round_trips_every_route_variant() {
        let policy = sample_policy();
        let decoded = policy_from_proto(policy_to_proto(policy.clone()).expect("encode policy"))
            .expect("decode policy");
        assert_json_equal(&policy, &decoded);
    }

    #[test]
    fn invalid_policy_enum_and_generation_are_rejected() {
        let mut encoded = policy_to_proto(sample_policy()).expect("encode policy");
        encoded.credential_routes[0].kind = proto::EgressKind::Unspecified as i32;
        assert!(policy_from_proto(encoded).is_err());

        assert!(generation_from_proto(proto::PolicyGeneration {
            policy_hash: String::new(),
            policy_version: 1,
        })
        .is_err());
    }

    #[test]
    fn strongly_typed_replication_events_round_trip() {
        let policy = ReplicatedPolicy {
            sandbox_id: uuid::Uuid::now_v7().to_string(),
            policy: sample_policy(),
        };
        let placement = contract::SandboxPlacement {
            sandbox_id: uuid::Uuid::now_v7().to_string(),
            node_id: "node-a".to_string(),
        };
        let payloads = vec![
            ReplicaEventPayload::SnapshotBegin { chunk_count: 1 },
            ReplicaEventPayload::SnapshotChunk {
                chunk_index: 0,
                snapshot: ReplicatedSnapshot {
                    policies: vec![policy.clone()],
                    placements: vec![placement.clone()],
                },
            },
            ReplicaEventPayload::SnapshotEnd,
            ReplicaEventPayload::Delta {
                mutation: ReplicaMutation::UpsertPolicy {
                    policy: policy.clone(),
                },
            },
            ReplicaEventPayload::Delta {
                mutation: ReplicaMutation::RemovePolicy {
                    sandbox_id: policy.sandbox_id.clone(),
                },
            },
            ReplicaEventPayload::Delta {
                mutation: ReplicaMutation::UpsertPlacement {
                    placement: placement.clone(),
                },
            },
            ReplicaEventPayload::Delta {
                mutation: ReplicaMutation::RemovePlacement {
                    sandbox_id: placement.sandbox_id.clone(),
                },
            },
            ReplicaEventPayload::Delta {
                mutation: ReplicaMutation::ReplacePlacements {
                    placements: vec![placement],
                },
            },
        ];

        for payload in payloads {
            let event = ReplicaEvent {
                protocol_version: 1,
                source_instance: "leader-a".to_string(),
                term: "term-a".to_string(),
                revision: 9,
                snapshot_digest: "digest-a".to_string(),
                payload,
            };
            let decoded = replica_event_from_proto(
                replica_event_to_proto(event.clone()).expect("encode replica event"),
            )
            .expect("decode replica event");
            assert_json_equal(&event, &decoded);
        }
    }
}
