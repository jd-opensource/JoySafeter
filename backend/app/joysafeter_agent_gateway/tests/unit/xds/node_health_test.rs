use super::*;

#[test]
fn readiness_requires_current_session_to_ack_cds_and_lds() {
    let registry = EnvoyNodeHealthRegistry::default();
    let old = NodeSessionId::from_raw(1);
    let current = NodeSessionId::from_raw(2);
    registry.connect("node-a", old);
    registry.connect("node-a", current);

    registry.mark_pending("node-a", current, ResourceType::Cluster, "cds-1");
    registry.mark_pending("node-a", current, ResourceType::Listener, "lds-1");
    registry.acknowledge("node-a", current, ResourceType::Cluster, "cds-1");
    assert!(!registry.snapshot()[0].ready);
    registry.acknowledge("node-a", current, ResourceType::Listener, "lds-1");
    assert!(registry.snapshot()[0].ready);

    registry.disconnect("node-a", old);
    assert!(registry.snapshot()[0].ready);
    registry.reject("node-a", old, ResourceType::Listener, "lds-1");
    assert!(registry.snapshot()[0].ready);
}

#[test]
fn a_new_response_revokes_readiness_until_acked() {
    let registry = EnvoyNodeHealthRegistry::default();
    let session = NodeSessionId::from_raw(1);
    registry.connect("node-a", session);
    for (resource_type, nonce) in [
        (ResourceType::Cluster, "cds-1"),
        (ResourceType::Listener, "lds-1"),
    ] {
        registry.mark_pending("node-a", session, resource_type, nonce);
        registry.acknowledge("node-a", session, resource_type, nonce);
    }
    assert!(registry.snapshot()[0].ready);

    registry.mark_pending("node-a", session, ResourceType::Listener, "lds-2");
    assert!(!registry.snapshot()[0].ready);
}

#[test]
fn disconnected_nodes_are_retained_only_while_authoritatively_assigned() {
    let registry = EnvoyNodeHealthRegistry::default();
    let session = NodeSessionId::from_raw(1);
    registry.connect("assigned", session);
    registry.connect("retired", session);
    registry.disconnect("assigned", session);
    registry.disconnect("retired", session);

    registry.retain_connected_or_assigned(&HashSet::from(["assigned".to_string()]));

    assert_eq!(
        registry.snapshot(),
        vec![EnvoyNodeStatus {
            node_id: "assigned".to_string(),
            connected: false,
            ready: false,
        }]
    );
}

#[test]
fn retention_never_removes_a_replacement_session() {
    let registry = EnvoyNodeHealthRegistry::default();
    let old = NodeSessionId::from_raw(1);
    let current = NodeSessionId::from_raw(2);
    registry.connect("node-a", old);
    registry.connect("node-a", current);

    registry.disconnect("node-a", old);
    registry.retain_connected_or_assigned(&HashSet::new());

    assert_eq!(registry.snapshot().len(), 1);
    assert!(registry.snapshot()[0].connected);
}
