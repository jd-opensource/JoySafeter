use joysafeter_orchestrator::ids::SandboxId;
use joysafeter_orchestrator::xds::ack_tracker::{
    AckDisposition, AckRecordOutcome, AckReport, AckTracker, RejectedAck,
};
use joysafeter_orchestrator::xds::control_plane::XdsControlPlane;
use joysafeter_orchestrator::xds::inventory::XdsResource;
use joysafeter_orchestrator::xds::model::{
    ApplyTicket, AuthorityEpoch, NodeId, PlacementRevision, PolicyGeneration, ResourceType,
    StreamId,
};
use prost_types::Any;
use uuid::Uuid;

fn source(path: &str) -> String {
    std::fs::read_to_string(path).unwrap_or_else(|error| panic!("read {path}: {error}"))
}

#[test]
fn ads_transport_uses_the_domain_control_plane_as_its_only_xds_state() {
    let transport = source("src/xds/transport.rs");
    assert!(transport.contains("XdsControlPlane"));
    assert!(!transport.contains("struct XdsState"));
    assert!(!transport.contains("enum XdsApplyStatus"));
    assert!(!transport.contains("sandbox_nodes:"));
    assert!(!transport.contains("apply_status:"));
}

fn sandbox(value: u128) -> SandboxId {
    SandboxId::from_uuid(Uuid::from_u128(value))
}

fn node(value: &str) -> NodeId {
    NodeId::new(value).unwrap()
}

fn resource(sandbox_id: SandboxId, resource_type: ResourceType, name: &str) -> XdsResource {
    XdsResource::new(
        sandbox_id,
        resource_type,
        name,
        Any {
            type_url: resource_type.type_url().to_string(),
            value: vec![1, 2, 3],
        },
    )
}

#[test]
fn placement_changes_emit_old_node_removals_and_new_node_upserts() {
    let sandbox_id = sandbox(1);
    let node_a = node("node-a");
    let node_b = node("node-b");
    let mut control_plane = XdsControlPlane::default();
    control_plane.upsert_resource(resource(
        sandbox_id,
        ResourceType::Listener,
        "sandbox-listener",
    ));

    let assigned = control_plane.assign_node(sandbox_id, node_a.clone());
    assert_eq!(assigned.revision(), PlacementRevision::new(1));
    assert!(assigned.removals().is_empty());
    assert_eq!(assigned.upserts_for(&node_a).len(), 1);

    let moved = control_plane.assign_node(sandbox_id, node_b.clone());
    assert_eq!(moved.revision(), PlacementRevision::new(2));
    assert_eq!(moved.removals_for(&node_a), ["sandbox-listener"]);
    assert_eq!(moved.upserts_for(&node_b).len(), 1);

    let removed = control_plane
        .remove_node(sandbox_id)
        .expect("owned sandbox");
    assert_eq!(removed.revision(), PlacementRevision::new(3));
    assert_eq!(removed.removals_for(&node_b), ["sandbox-listener"]);
    assert!(removed.upserts().is_empty());
}

#[test]
fn late_placement_assignment_makes_existing_inventory_visible() {
    let sandbox_id = sandbox(2);
    let node_a = node("node-a");
    let mut control_plane = XdsControlPlane::default();
    control_plane.upsert_resource(resource(
        sandbox_id,
        ResourceType::Cluster,
        "sandbox-cluster",
    ));

    assert!(control_plane.resources_for_node(&node_a).is_empty());
    let assigned = control_plane.assign_node(sandbox_id, node_a.clone());
    assert_eq!(assigned.upserts_for(&node_a).len(), 1);
    assert_eq!(control_plane.resources_for_node(&node_a).len(), 1);
}

#[test]
fn convergence_requires_every_owner_and_resource_type() {
    let sandbox_id = sandbox(3);
    let node_a = node("node-a");
    let node_b = node("node-b");
    let ticket = ApplyTicket::new(
        sandbox_id,
        AuthorityEpoch::new(7),
        PolicyGeneration::new(11),
        PlacementRevision::new(5),
        [node_a.clone(), node_b.clone()],
        [ResourceType::Cluster, ResourceType::Listener],
    );
    let mut tracker = AckTracker::default();
    tracker.begin(ticket.clone());
    tracker.register_stream(node_a.clone(), StreamId::new(100));
    tracker.register_stream(node_b.clone(), StreamId::new(200));

    for (node_id, stream_id, resource_type) in [
        (node_a.clone(), StreamId::new(100), ResourceType::Cluster),
        (node_a.clone(), StreamId::new(100), ResourceType::Listener),
        (node_b.clone(), StreamId::new(200), ResourceType::Cluster),
    ] {
        assert_eq!(
            tracker.record(AckReport::for_ticket(
                &ticket,
                node_id,
                stream_id,
                resource_type,
                AckDisposition::Ack,
            )),
            AckRecordOutcome::Pending
        );
    }

    assert_eq!(
        tracker.record(AckReport::for_ticket(
            &ticket,
            node_b,
            StreamId::new(200),
            ResourceType::Listener,
            AckDisposition::Ack,
        )),
        AckRecordOutcome::Converged
    );
}

#[test]
fn stale_or_non_owner_ack_cannot_complete_current_generation() {
    let sandbox_id = sandbox(4);
    let owner = node("node-a");
    let ticket = ApplyTicket::new(
        sandbox_id,
        AuthorityEpoch::new(7),
        PolicyGeneration::new(11),
        PlacementRevision::new(5),
        [owner.clone()],
        [ResourceType::Listener],
    );
    let mut tracker = AckTracker::default();
    tracker.begin(ticket.clone());
    tracker.register_stream(owner.clone(), StreamId::new(10));
    tracker.register_stream(owner.clone(), StreamId::new(11));

    assert_eq!(
        tracker.record(AckReport::for_ticket(
            &ticket,
            owner.clone(),
            StreamId::new(10),
            ResourceType::Listener,
            AckDisposition::Ack,
        )),
        AckRecordOutcome::Rejected(RejectedAck::StaleStream)
    );

    let mut stale_epoch = AckReport::for_ticket(
        &ticket,
        owner.clone(),
        StreamId::new(11),
        ResourceType::Listener,
        AckDisposition::Ack,
    );
    stale_epoch.authority_epoch = AuthorityEpoch::new(6);
    assert_eq!(
        tracker.record(stale_epoch),
        AckRecordOutcome::Rejected(RejectedAck::StaleEpoch)
    );

    let mut stale_generation = AckReport::for_ticket(
        &ticket,
        owner.clone(),
        StreamId::new(11),
        ResourceType::Listener,
        AckDisposition::Ack,
    );
    stale_generation.generation = PolicyGeneration::new(10);
    assert_eq!(
        tracker.record(stale_generation),
        AckRecordOutcome::Rejected(RejectedAck::StaleGeneration)
    );

    let mut stale_placement = AckReport::for_ticket(
        &ticket,
        owner.clone(),
        StreamId::new(11),
        ResourceType::Listener,
        AckDisposition::Ack,
    );
    stale_placement.placement_revision = PlacementRevision::new(4);
    assert_eq!(
        tracker.record(stale_placement),
        AckRecordOutcome::Rejected(RejectedAck::StalePlacement)
    );

    assert_eq!(
        tracker.record(AckReport::for_ticket(
            &ticket,
            node("node-z"),
            StreamId::new(99),
            ResourceType::Listener,
            AckDisposition::Ack,
        )),
        AckRecordOutcome::Rejected(RejectedAck::NonOwner)
    );
}

#[test]
fn replacing_a_stream_invalidates_that_nodes_partial_ack_quorum() {
    let sandbox_id = sandbox(5);
    let owner = node("node-a");
    let ticket = ApplyTicket::new(
        sandbox_id,
        AuthorityEpoch::new(7),
        PolicyGeneration::new(11),
        PlacementRevision::new(5),
        [owner.clone()],
        [ResourceType::Cluster, ResourceType::Listener],
    );
    let mut tracker = AckTracker::default();
    tracker.begin(ticket.clone());
    tracker.register_stream(owner.clone(), StreamId::new(10));
    assert_eq!(
        tracker.record(AckReport::for_ticket(
            &ticket,
            owner.clone(),
            StreamId::new(10),
            ResourceType::Cluster,
            AckDisposition::Ack,
        )),
        AckRecordOutcome::Pending
    );

    tracker.register_stream(owner.clone(), StreamId::new(11));
    assert_eq!(
        tracker.record(AckReport::for_ticket(
            &ticket,
            owner.clone(),
            StreamId::new(11),
            ResourceType::Listener,
            AckDisposition::Ack,
        )),
        AckRecordOutcome::Pending,
        "a new stream must not inherit ACKs recorded on the replaced stream"
    );
    assert_eq!(
        tracker.record(AckReport::for_ticket(
            &ticket,
            owner,
            StreamId::new(11),
            ResourceType::Cluster,
            AckDisposition::Ack,
        )),
        AckRecordOutcome::Converged
    );
}
