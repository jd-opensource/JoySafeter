use super::*;

#[test]
fn invalid_ack_maps_to_conflict() {
    assert_eq!(
        replication_error(ReplicationError::InvalidAck).status(),
        StatusCode::CONFLICT
    );
}
