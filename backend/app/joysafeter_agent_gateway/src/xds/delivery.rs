//! Exact xDS delivery attempts and ACK/NACK quorum tracking.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

use thiserror::Error;

use crate::ids::SandboxId;

use super::model::{DeliveryGeneration, ResourceType};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeliveryRequest {
    pub authority_epoch: u64,
    pub sandbox_id: SandboxId,
    pub generation: DeliveryGeneration,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeliveryTarget {
    AnyNode,
    Node(String),
    Unavailable,
}

impl DeliveryTarget {
    fn validate(&self) -> Result<(), DeliveryError> {
        if matches!(self, Self::Node(node) if node.trim().is_empty()) {
            return Err(DeliveryError::MissingOwnerNode);
        }
        Ok(())
    }

    fn accepts(&self, node: &str) -> bool {
        match self {
            Self::AnyNode => true,
            Self::Node(owner_node) => owner_node == node,
            Self::Unavailable => false,
        }
    }
}

impl DeliveryRequest {
    pub fn validate(&self) -> Result<(), DeliveryError> {
        if self.authority_epoch == 0 {
            return Err(DeliveryError::InvalidAuthorityEpoch);
        }
        if self.generation.policy_hash.is_empty() || self.generation.policy_version <= 0 {
            return Err(DeliveryError::InvalidGeneration);
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DeliveryAttempt {
    pub sandbox_id: SandboxId,
    pub attempt_id: DeliveryAttemptId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeliveredResource {
    pub name: String,
    pub owner: super::model::ResourceOwner,
    pub removed: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct DeliveryAttemptId(u64);

impl DeliveryAttemptId {
    pub const fn from_raw(value: u64) -> Self {
        Self(value)
    }

    pub const fn as_u64(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct NodeSessionId(u64);

impl NodeSessionId {
    pub const fn from_raw(value: u64) -> Self {
        Self(value)
    }

    pub const fn as_u64(self) -> u64 {
        self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct DeliveryKey {
    pub authority_epoch: u64,
    pub sandbox_id: SandboxId,
    pub generation: DeliveryGeneration,
    pub owner_node: String,
    pub node_session: NodeSessionId,
    pub attempt_id: DeliveryAttemptId,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResponseReceipt {
    pub nonce: String,
    pub key: DeliveryKey,
    pub resource_type: ResourceType,
    pub transmitted_names: Vec<String>,
    pub removed_names: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeliveryOutcome {
    Pending,
    Acked,
    Nacked {
        resource_type: ResourceType,
        reason: String,
    },
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ReceiptOutcome {
    Accepted,
    Completed,
    Duplicate,
    Stale,
}

#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum DeliveryError {
    #[error("xDS delivery authority epoch must be positive")]
    InvalidAuthorityEpoch,
    #[error("xDS delivery policy generation is invalid")]
    InvalidGeneration,
    #[error("xDS delivery owner node must not be empty")]
    MissingOwnerNode,
    #[error("xDS delivery node session must be positive")]
    InvalidNodeSession,
    #[error("xDS delivery attempt id must be positive")]
    InvalidAttemptId,
    #[error("xDS delivery attempt must require at least one resource type")]
    EmptyQuorum,
    #[error("xDS removal has no known delivered policy generation")]
    MissingDeliveryContext,
    #[error("xDS delivery world revision must be positive")]
    InvalidWorldRevision,
    #[error("xDS delivery attempt is stale")]
    StaleAttempt,
    #[error("xDS policy generation is older than the accepted generation")]
    StaleGeneration,
    #[error("xDS policy generation reuses a version with a different policy hash")]
    ConflictingGeneration,
    #[error("xDS policy generation was already removed")]
    RemovedGeneration,
    #[error("xDS removal generation is newer than the accepted generation")]
    RemovalGenerationAhead,
    #[error("xDS response receipt nonce must not be empty")]
    MissingNonce,
    #[error("xDS response receipt must contain transmitted or removed resources")]
    EmptyReceipt,
    #[error("xDS response receipt contains duplicate resource names")]
    DuplicateResourceName,
    #[error("xDS response receipt type is not required by the delivery attempt")]
    UnexpectedResourceType,
    #[error("xDS response nonce was reused with conflicting receipt content")]
    ConflictingNonce,
}

#[derive(Debug, Clone)]
struct AttemptState {
    key: DeliveryKey,
    required_types: HashSet<ResourceType>,
    acknowledged_types: HashSet<ResourceType>,
    outcome: DeliveryOutcome,
}

#[derive(Debug, Default)]
pub struct DeliveryTracker {
    attempts: HashMap<SandboxId, AttemptState>,
    receipts: HashMap<String, Vec<ResponseReceipt>>,
}

#[derive(Debug, Clone)]
struct PendingAttempt {
    request: DeliveryRequest,
    attempt_id: DeliveryAttemptId,
    target: DeliveryTarget,
    required_types: HashSet<ResourceType>,
    published_revision: Option<u64>,
    bound_key: Option<DeliveryKey>,
    started_at: Instant,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) struct DeliveryMetricsSnapshot {
    pub pending_delivery_count: usize,
    pub oldest_pending_delivery_age: Duration,
}

#[derive(Debug, Default)]
pub struct DeliveryCoordinator {
    tracker: DeliveryTracker,
    attempts: HashMap<SandboxId, PendingAttempt>,
    node_sessions: HashMap<String, NodeSessionId>,
    next_attempt_id: u64,
    next_session_id: u64,
    generation_watermarks: HashMap<SandboxId, GenerationWatermark>,
}

#[derive(Debug, Clone)]
struct GenerationWatermark {
    generation: Option<DeliveryGeneration>,
    removed: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ApplyAdmission {
    New,
    Existing(DeliveryAttempt),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RemoveAdmission {
    Remove,
    AlreadyRemoved,
    Superseded,
}

impl DeliveryCoordinator {
    pub fn admit_apply(
        &mut self,
        request: &DeliveryRequest,
    ) -> Result<ApplyAdmission, DeliveryError> {
        request.validate()?;
        if let Some(watermark) = self.generation_watermarks.get(&request.sandbox_id) {
            if let Some(current) = &watermark.generation {
                if request.generation.policy_version < current.policy_version {
                    return Err(DeliveryError::StaleGeneration);
                }
                if request.generation.policy_version == current.policy_version
                    && request.generation.policy_hash != current.policy_hash
                {
                    return Err(DeliveryError::ConflictingGeneration);
                }
                if watermark.removed && request.generation.policy_version == current.policy_version
                {
                    return Err(DeliveryError::RemovedGeneration);
                }
                if request.generation == *current {
                    if let Some(pending) = self.attempts.get(&request.sandbox_id) {
                        return Ok(ApplyAdmission::Existing(DeliveryAttempt {
                            sandbox_id: request.sandbox_id,
                            attempt_id: pending.attempt_id,
                        }));
                    }
                }
            }
        }
        self.generation_watermarks.insert(
            request.sandbox_id,
            GenerationWatermark {
                generation: Some(request.generation.clone()),
                removed: false,
            },
        );
        Ok(ApplyAdmission::New)
    }

    pub fn admit_remove(
        &self,
        sandbox_id: SandboxId,
        expected_generation: Option<&DeliveryGeneration>,
    ) -> Result<RemoveAdmission, DeliveryError> {
        let Some(expected) = expected_generation else {
            return Ok(RemoveAdmission::Remove);
        };
        if expected.policy_hash.is_empty() || expected.policy_version <= 0 {
            return Err(DeliveryError::InvalidGeneration);
        }
        let Some(watermark) = self.generation_watermarks.get(&sandbox_id) else {
            return Ok(RemoveAdmission::Remove);
        };
        let Some(current) = &watermark.generation else {
            return Ok(RemoveAdmission::Remove);
        };
        if expected.policy_version < current.policy_version {
            return Ok(RemoveAdmission::Superseded);
        }
        if expected.policy_version > current.policy_version {
            return Err(DeliveryError::RemovalGenerationAhead);
        }
        if expected.policy_hash != current.policy_hash {
            return Err(DeliveryError::ConflictingGeneration);
        }
        if watermark.removed {
            return Ok(RemoveAdmission::AlreadyRemoved);
        }
        Ok(RemoveAdmission::Remove)
    }

    pub fn mark_removed(
        &mut self,
        sandbox_id: SandboxId,
        expected_generation: Option<&DeliveryGeneration>,
    ) {
        let generation = expected_generation.cloned().or_else(|| {
            self.generation_watermarks
                .get(&sandbox_id)
                .and_then(|watermark| watermark.generation.clone())
                .or_else(|| {
                    self.attempts
                        .get(&sandbox_id)
                        .map(|attempt| attempt.request.generation.clone())
                })
        });
        if let Some(generation) = generation {
            self.generation_watermarks.insert(
                sandbox_id,
                GenerationWatermark {
                    generation: Some(generation),
                    removed: true,
                },
            );
        } else {
            // DELETE is idempotent. If no policy generation has ever been
            // admitted, there is nothing to fence. Persisting an unversioned
            // tombstone here would let a cleanup racing the first placement
            // permanently reject the initial policy publication.
            self.generation_watermarks.remove(&sandbox_id);
        }
    }

    pub fn replace_generation_watermarks<'a>(
        &mut self,
        requests: impl IntoIterator<Item = &'a DeliveryRequest>,
    ) {
        self.generation_watermarks = requests
            .into_iter()
            .map(|request| {
                (
                    request.sandbox_id,
                    GenerationWatermark {
                        generation: Some(request.generation.clone()),
                        removed: false,
                    },
                )
            })
            .collect();
    }

    pub fn clear_pending(&mut self) {
        self.tracker = DeliveryTracker::default();
        self.attempts.clear();
    }

    pub fn open_node_session(&mut self, node: impl Into<String>) -> NodeSessionId {
        self.next_session_id = self.next_session_id.saturating_add(1).max(1);
        let session = NodeSessionId::from_raw(self.next_session_id);
        self.node_sessions.insert(node.into(), session);
        session
    }

    pub fn is_current_node_session(&self, node: &str, session: NodeSessionId) -> bool {
        self.node_sessions.get(node) == Some(&session)
    }

    pub fn close_node_session(&mut self, node: &str, session: NodeSessionId) {
        if self.node_sessions.get(node) == Some(&session) {
            self.node_sessions.remove(node);
        }
    }

    pub fn begin_attempt(
        &mut self,
        request: DeliveryRequest,
        target: DeliveryTarget,
        required_types: HashSet<ResourceType>,
    ) -> Result<DeliveryAttempt, DeliveryError> {
        request.validate()?;
        target.validate()?;
        if required_types.is_empty() {
            return Err(DeliveryError::EmptyQuorum);
        }
        self.next_attempt_id = self.next_attempt_id.saturating_add(1).max(1);
        let attempt_id = DeliveryAttemptId::from_raw(self.next_attempt_id);
        self.tracker.forget(request.sandbox_id);
        self.attempts.insert(
            request.sandbox_id,
            PendingAttempt {
                request: request.clone(),
                attempt_id,
                target,
                required_types,
                published_revision: None,
                bound_key: None,
                started_at: Instant::now(),
            },
        );
        Ok(DeliveryAttempt {
            sandbox_id: request.sandbox_id,
            attempt_id,
        })
    }

    pub fn begin_removal(
        &mut self,
        sandbox_id: SandboxId,
        target: DeliveryTarget,
        required_types: HashSet<ResourceType>,
    ) -> Result<DeliveryAttempt, DeliveryError> {
        let previous = self
            .attempts
            .get(&sandbox_id)
            .cloned()
            .ok_or(DeliveryError::MissingDeliveryContext)?;
        self.begin_attempt(previous.request, target, required_types)
    }

    pub fn retarget_current(
        &mut self,
        sandbox_id: SandboxId,
        target: DeliveryTarget,
        world_revision: u64,
    ) -> Result<Option<DeliveryAttempt>, DeliveryError> {
        target.validate()?;
        let Some(previous) = self.attempts.get(&sandbox_id).cloned() else {
            return Ok(None);
        };
        if previous.required_types.is_empty() {
            return Ok(None);
        }
        if world_revision == 0 {
            return Err(DeliveryError::InvalidWorldRevision);
        }
        let required_types = previous.required_types;
        let attempt = self.begin_attempt(previous.request, target, required_types.clone())?;
        self.mark_published(attempt, world_revision, required_types)?;
        Ok(Some(attempt))
    }

    pub fn suspend_current(&mut self, sandbox_id: SandboxId) {
        let Some(pending) = self.attempts.get_mut(&sandbox_id) else {
            return;
        };
        pending.target = DeliveryTarget::Unavailable;
        pending.bound_key = None;
        self.tracker.forget(sandbox_id);
    }

    pub fn current_request(&self, sandbox_id: SandboxId) -> Option<DeliveryRequest> {
        self.attempts
            .get(&sandbox_id)
            .map(|pending| pending.request.clone())
    }

    pub fn pending_sandboxes_for(
        &self,
        node: &str,
        resource_type: ResourceType,
    ) -> HashSet<SandboxId> {
        self.attempts
            .iter()
            .filter(|(_, pending)| {
                pending.published_revision.is_some()
                    && pending.target.accepts(node)
                    && pending.required_types.contains(&resource_type)
                    && match pending.bound_key.as_ref() {
                        None => true,
                        Some(key) => self.tracker.outcome(key) == Some(DeliveryOutcome::Pending),
                    }
            })
            .map(|(sandbox_id, _)| *sandbox_id)
            .collect()
    }

    pub fn mark_published(
        &mut self,
        attempt: DeliveryAttempt,
        world_revision: u64,
        required_types: HashSet<ResourceType>,
    ) -> Result<(), DeliveryError> {
        if world_revision == 0 {
            return Err(DeliveryError::InvalidWorldRevision);
        }
        if required_types.is_empty() {
            return Err(DeliveryError::EmptyQuorum);
        }
        let pending = self
            .attempts
            .get_mut(&attempt.sandbox_id)
            .filter(|pending| pending.attempt_id == attempt.attempt_id)
            .ok_or(DeliveryError::StaleAttempt)?;
        pending.required_types = required_types;
        pending.published_revision = Some(world_revision);
        pending.bound_key = None;
        self.tracker.forget(attempt.sandbox_id);
        Ok(())
    }

    pub fn record_response(
        &mut self,
        node: &str,
        session: NodeSessionId,
        nonce: &str,
        world_revision: u64,
        resource_type: ResourceType,
        resources: &[DeliveredResource],
    ) -> Result<ReceiptOutcome, DeliveryError> {
        if self.node_sessions.get(node) != Some(&session) {
            return Ok(ReceiptOutcome::Stale);
        }
        let mut by_sandbox = HashMap::<SandboxId, (Vec<String>, Vec<String>)>::new();
        for resource in resources {
            let super::model::ResourceOwner::Sandbox(sandbox_id) = resource.owner else {
                continue;
            };
            let names = by_sandbox.entry(sandbox_id).or_default();
            if resource.removed {
                names.1.push(resource.name.clone());
            } else {
                names.0.push(resource.name.clone());
            }
        }

        let mut accepted = false;
        for (sandbox_id, (transmitted_names, removed_names)) in by_sandbox {
            let Some(pending) = self.attempts.get_mut(&sandbox_id) else {
                continue;
            };
            if !pending
                .published_revision
                .is_some_and(|published| world_revision >= published)
            {
                continue;
            }
            if !pending.target.accepts(node) || !pending.required_types.contains(&resource_type) {
                continue;
            }
            let key = DeliveryKey {
                authority_epoch: pending.request.authority_epoch,
                sandbox_id,
                generation: pending.request.generation.clone(),
                owner_node: node.to_string(),
                node_session: session,
                attempt_id: pending.attempt_id,
            };
            if pending.bound_key.as_ref() != Some(&key) {
                self.tracker
                    .begin_attempt(key.clone(), pending.required_types.clone())?;
                pending.bound_key = Some(key.clone());
            }
            let scoped_nonce = scoped_nonce(session, nonce);
            let outcome = self.tracker.record_response(ResponseReceipt {
                nonce: scoped_nonce,
                key,
                resource_type,
                transmitted_names,
                removed_names,
            })?;
            accepted |= matches!(
                outcome,
                ReceiptOutcome::Accepted | ReceiptOutcome::Duplicate
            );
        }
        Ok(if accepted {
            ReceiptOutcome::Accepted
        } else {
            ReceiptOutcome::Stale
        })
    }

    pub fn acknowledge(
        &mut self,
        node: &str,
        session: NodeSessionId,
        nonce: &str,
    ) -> ReceiptOutcome {
        if self.node_sessions.get(node) != Some(&session) {
            return ReceiptOutcome::Stale;
        }
        self.tracker.acknowledge(&scoped_nonce(session, nonce))
    }

    pub fn reject(
        &mut self,
        node: &str,
        session: NodeSessionId,
        nonce: &str,
        reason: impl Into<String>,
    ) -> ReceiptOutcome {
        if self.node_sessions.get(node) != Some(&session) {
            return ReceiptOutcome::Stale;
        }
        self.tracker
            .reject(&scoped_nonce(session, nonce), reason.into())
    }

    pub fn outcome(&self, attempt: DeliveryAttempt) -> Option<DeliveryOutcome> {
        let pending = self.attempts.get(&attempt.sandbox_id)?;
        let key = pending.bound_key.as_ref()?;
        if key.attempt_id != attempt.attempt_id {
            return None;
        }
        self.tracker.outcome(key)
    }

    pub fn forget(&mut self, sandbox_id: SandboxId) {
        self.attempts.remove(&sandbox_id);
        self.tracker.forget(sandbox_id);
        // Terminal retirement: drop the generation tombstone too. SandboxIds are
        // unique per sandbox and never reused, so no future apply needs to be
        // fenced against this id — keeping the tombstone would leak one map entry
        // per sandbox for the leader's lifetime. (Fixes L1.)
        self.generation_watermarks.remove(&sandbox_id);
    }

    pub(crate) fn metrics_snapshot(&self) -> DeliveryMetricsSnapshot {
        let now = Instant::now();
        let mut pending_delivery_count = 0;
        let mut oldest_pending_delivery_age = Duration::ZERO;
        for pending in self.attempts.values() {
            if pending.published_revision.is_none() {
                continue;
            }
            let is_pending = match pending.bound_key.as_ref() {
                Some(key) => self.tracker.outcome(key) == Some(DeliveryOutcome::Pending),
                None => true,
            };
            if !is_pending {
                continue;
            }
            pending_delivery_count += 1;
            oldest_pending_delivery_age =
                oldest_pending_delivery_age.max(now.saturating_duration_since(pending.started_at));
        }
        DeliveryMetricsSnapshot {
            pending_delivery_count,
            oldest_pending_delivery_age,
        }
    }
}

fn scoped_nonce(session: NodeSessionId, nonce: &str) -> String {
    format!("{}:{nonce}", session.as_u64())
}

mod tracker;

#[cfg(test)]
#[path = "../../tests/unit/xds/delivery_test.rs"]
mod tests;
