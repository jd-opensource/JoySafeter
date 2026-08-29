use joysafeter_orchestrator::xds::authority::{AuthorityState, AuthorityStateMachine};
use joysafeter_orchestrator::xds::metrics::XdsMetrics;
use joysafeter_orchestrator::xds::model::AuthorityEpoch;

#[test]
fn authority_must_recover_before_serving_and_revoke_before_standby() {
    let mut authority = AuthorityStateMachine::default();
    assert_eq!(authority.state(), AuthorityState::Standby);

    authority.acquire(AuthorityEpoch::new(3)).unwrap();
    assert_eq!(
        authority.state(),
        AuthorityState::Acquired(AuthorityEpoch::new(3))
    );
    assert!(authority.ready_fence().is_none());

    authority.begin_recovery().unwrap();
    assert_eq!(
        authority.state(),
        AuthorityState::Recovering(AuthorityEpoch::new(3))
    );
    authority.mark_ready().unwrap();
    assert_eq!(
        authority.state(),
        AuthorityState::Ready(AuthorityEpoch::new(3))
    );
    assert_eq!(
        authority.ready_fence().unwrap().epoch(),
        AuthorityEpoch::new(3)
    );

    authority.begin_revoke().unwrap();
    assert_eq!(
        authority.state(),
        AuthorityState::Revoking(AuthorityEpoch::new(3))
    );
    assert!(authority.ready_fence().is_none());
    authority.complete_revoke().unwrap();
    assert_eq!(authority.state(), AuthorityState::Standby);
}

#[test]
fn authority_rejects_illegal_or_stale_transitions() {
    let mut authority = AuthorityStateMachine::default();
    assert!(authority.mark_ready().is_err());
    authority.acquire(AuthorityEpoch::new(4)).unwrap();
    assert!(authority.acquire(AuthorityEpoch::new(4)).is_err());
    authority.begin_recovery().unwrap();
    authority.mark_ready().unwrap();
    assert!(authority.acquire(AuthorityEpoch::new(3)).is_err());
}

#[test]
fn xds_metrics_snapshot_contains_only_counts_and_state() {
    let metrics = XdsMetrics::default();
    metrics.set_authority_state(AuthorityState::Ready(AuthorityEpoch::new(9)));
    metrics.stream_opened();
    metrics.authentication_failed();
    metrics.ack_recorded();
    metrics.nack_recorded();
    metrics.reconcile_completed(true);

    let snapshot = metrics.snapshot();
    assert_eq!(snapshot.authority_epoch, 9);
    assert_eq!(snapshot.active_streams, 1);
    assert_eq!(snapshot.authentication_failures, 1);
    assert_eq!(snapshot.acks, 1);
    assert_eq!(snapshot.nacks, 1);
    assert_eq!(snapshot.reconcile_successes, 1);
}
