use std::collections::{BTreeSet, HashMap};

use crate::ids::SandboxId;

use super::model::{
    ApplyTicket, AuthorityEpoch, NodeId, PlacementRevision, PolicyGeneration, ResourceType,
    StreamId,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AckDisposition {
    Ack,
    Nack(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AckReport {
    pub sandbox_id: SandboxId,
    pub authority_epoch: AuthorityEpoch,
    pub generation: PolicyGeneration,
    pub placement_revision: PlacementRevision,
    pub node_id: NodeId,
    pub stream_id: StreamId,
    pub resource_type: ResourceType,
    pub disposition: AckDisposition,
}

impl AckReport {
    pub fn for_ticket(
        ticket: &ApplyTicket,
        node_id: NodeId,
        stream_id: StreamId,
        resource_type: ResourceType,
        disposition: AckDisposition,
    ) -> Self {
        Self {
            sandbox_id: ticket.sandbox_id(),
            authority_epoch: ticket.authority_epoch(),
            generation: ticket.generation(),
            placement_revision: ticket.placement_revision(),
            node_id,
            stream_id,
            resource_type,
            disposition,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RejectedAck {
    MissingTicket,
    NonOwner,
    UnexpectedResourceType,
    StaleEpoch,
    StaleGeneration,
    StalePlacement,
    StaleStream,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum AckRecordOutcome {
    Pending,
    Converged,
    Nacked(String),
    Rejected(RejectedAck),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ApplyStatus {
    Pending {
        min_version: u64,
        placement_revision: PlacementRevision,
        expected_nodes: BTreeSet<NodeId>,
        required_types: BTreeSet<ResourceType>,
        acknowledged: BTreeSet<(NodeId, ResourceType)>,
    },
    Acked,
    Nacked(String),
}

struct PendingApply {
    ticket: ApplyTicket,
    acknowledgements: BTreeSet<(NodeId, ResourceType)>,
}

#[derive(Default)]
pub struct AckTracker {
    pending: HashMap<SandboxId, PendingApply>,
    completed: HashMap<SandboxId, ApplyStatus>,
    streams: HashMap<NodeId, StreamId>,
    last_stream: Option<(NodeId, StreamId)>,
}

impl AckTracker {
    pub fn begin(&mut self, ticket: ApplyTicket) {
        self.completed.remove(&ticket.sandbox_id());
        self.pending.insert(
            ticket.sandbox_id(),
            PendingApply {
                ticket,
                acknowledgements: BTreeSet::new(),
            },
        );
    }

    pub fn register_stream(&mut self, node_id: NodeId, stream_id: StreamId) {
        let replaced = self.streams.insert(node_id.clone(), stream_id);
        if replaced.is_some_and(|previous| previous != stream_id) {
            for pending in self.pending.values_mut() {
                pending
                    .acknowledgements
                    .retain(|(acked_node, _)| acked_node != &node_id);
            }
        }
        self.last_stream = Some((node_id, stream_id));
    }

    pub fn unregister_stream(&mut self, node_id: &NodeId, stream_id: StreamId) {
        if self.streams.get(node_id) == Some(&stream_id) {
            self.streams.remove(node_id);
        }
        if self.last_stream.as_ref() == Some(&(node_id.clone(), stream_id)) {
            self.last_stream = self
                .streams
                .iter()
                .next()
                .map(|(node_id, stream_id)| (node_id.clone(), *stream_id));
        }
    }

    pub fn latest_stream_node(&self) -> Option<NodeId> {
        self.last_stream
            .as_ref()
            .map(|(node_id, _)| node_id.clone())
    }

    pub fn pending_sandbox_ids(&self) -> Vec<SandboxId> {
        self.pending.keys().copied().collect()
    }

    pub fn ticket(&self, sandbox_id: SandboxId) -> Option<ApplyTicket> {
        self.pending
            .get(&sandbox_id)
            .map(|pending| pending.ticket.clone())
    }

    pub fn retarget(
        &mut self,
        sandbox_id: SandboxId,
        placement_revision: PlacementRevision,
        expected_nodes: impl IntoIterator<Item = NodeId>,
    ) {
        let Some(existing) = self.pending.get(&sandbox_id) else {
            return;
        };
        let ticket = ApplyTicket::new(
            sandbox_id,
            existing.ticket.authority_epoch(),
            existing.ticket.generation(),
            placement_revision,
            expected_nodes,
            existing.ticket.required_types().iter().copied(),
        );
        self.begin(ticket);
    }

    pub fn forget(&mut self, sandbox_id: SandboxId) {
        self.pending.remove(&sandbox_id);
        self.completed.remove(&sandbox_id);
    }

    pub fn revoke(&mut self) {
        self.pending.clear();
        self.completed.clear();
        self.streams.clear();
        self.last_stream = None;
    }

    pub fn status(&self, sandbox_id: SandboxId) -> Option<ApplyStatus> {
        if let Some(status) = self.completed.get(&sandbox_id) {
            return Some(status.clone());
        }
        self.pending
            .get(&sandbox_id)
            .map(|pending| ApplyStatus::Pending {
                min_version: pending.ticket.generation().get(),
                placement_revision: pending.ticket.placement_revision(),
                expected_nodes: pending.ticket.expected_nodes().clone(),
                required_types: pending.ticket.required_types().clone(),
                acknowledged: pending.acknowledgements.clone(),
            })
    }

    pub fn record(&mut self, report: AckReport) -> AckRecordOutcome {
        let Some(pending) = self.pending.get_mut(&report.sandbox_id) else {
            return AckRecordOutcome::Rejected(RejectedAck::MissingTicket);
        };
        if !pending.ticket.expected_nodes().contains(&report.node_id) {
            return AckRecordOutcome::Rejected(RejectedAck::NonOwner);
        }
        if !pending
            .ticket
            .required_types()
            .contains(&report.resource_type)
        {
            return AckRecordOutcome::Rejected(RejectedAck::UnexpectedResourceType);
        }
        if report.authority_epoch != pending.ticket.authority_epoch() {
            return AckRecordOutcome::Rejected(RejectedAck::StaleEpoch);
        }
        if report.generation < pending.ticket.generation() {
            return AckRecordOutcome::Rejected(RejectedAck::StaleGeneration);
        }
        if report.placement_revision != pending.ticket.placement_revision() {
            return AckRecordOutcome::Rejected(RejectedAck::StalePlacement);
        }
        if self.streams.get(&report.node_id) != Some(&report.stream_id) {
            return AckRecordOutcome::Rejected(RejectedAck::StaleStream);
        }

        let outcome = match report.disposition {
            AckDisposition::Nack(reason) => AckRecordOutcome::Nacked(reason),
            AckDisposition::Ack => {
                pending
                    .acknowledgements
                    .insert((report.node_id, report.resource_type));
                let converged = pending.ticket.expected_nodes().iter().all(|node_id| {
                    pending.ticket.required_types().iter().all(|resource_type| {
                        pending
                            .acknowledgements
                            .contains(&(node_id.clone(), *resource_type))
                    })
                });
                if converged {
                    AckRecordOutcome::Converged
                } else {
                    AckRecordOutcome::Pending
                }
            }
        };

        match &outcome {
            AckRecordOutcome::Converged => {
                self.pending.remove(&report.sandbox_id);
                self.completed.insert(report.sandbox_id, ApplyStatus::Acked);
            }
            AckRecordOutcome::Nacked(reason) => {
                self.pending.remove(&report.sandbox_id);
                self.completed
                    .insert(report.sandbox_id, ApplyStatus::Nacked(reason.clone()));
            }
            AckRecordOutcome::Pending | AckRecordOutcome::Rejected(_) => {}
        }
        outcome
    }
}
