use super::*;

/// Drive a fresh authority through a full recovery to `Ready`, returning the
/// epoch it settled on.
fn drive_to_ready(authority: &XdsAuthority) -> u64 {
    let guard = authority.begin_staging().expect("begin staging");
    authority
        .begin_recovery_serving(&guard)
        .expect("begin recovery serving");
    authority.mark_ready(&guard).expect("mark ready");
    guard.epoch()
}

/// Extract the error from a staging attempt expected to fail. `RecoveryAuthorityGuard`
/// is intentionally not `Debug`, so `unwrap_err` cannot be used directly.
fn staging_err(result: Result<RecoveryAuthorityGuard, AuthorityError>) -> AuthorityError {
    match result {
        Ok(_) => panic!("expected staging to be rejected"),
        Err(err) => err,
    }
}

#[test]
fn new_authority_starts_in_standby() {
    let authority = XdsAuthority::standalone();
    assert_eq!(authority.phase(), AuthorityPhase::Standby);
    assert_eq!(authority.phase().epoch(), None);
    assert!(!authority.phase().serves_ads());
    assert!(authority.mutation_guard().is_none());
}

#[test]
fn full_lifecycle_standby_to_ready_uses_epoch_one() {
    let authority = XdsAuthority::standalone();

    let guard = authority.begin_staging().expect("begin staging");
    assert_eq!(guard.epoch(), 1);
    assert_eq!(authority.phase(), AuthorityPhase::Staging { epoch: 1 });
    assert!(!authority.phase().serves_ads());

    authority
        .begin_recovery_serving(&guard)
        .expect("begin recovery serving");
    assert_eq!(
        authority.phase(),
        AuthorityPhase::RecoveryServing { epoch: 1 }
    );
    assert!(authority.phase().serves_ads());

    authority.mark_ready(&guard).expect("mark ready");
    assert_eq!(authority.phase(), AuthorityPhase::Ready { epoch: 1 });
    assert!(authority.phase().serves_ads());
}

#[test]
fn begin_staging_is_rejected_from_non_terminal_phases() {
    let authority = XdsAuthority::standalone();
    let guard = authority.begin_staging().expect("begin staging");

    // Already Staging.
    assert_eq!(
        staging_err(authority.begin_staging()),
        AuthorityError::InvalidTransition {
            from: AuthorityPhase::Staging { epoch: 1 },
            target: "Staging",
        }
    );

    // RecoveryServing.
    authority.begin_recovery_serving(&guard).unwrap();
    assert!(matches!(
        staging_err(authority.begin_staging()),
        AuthorityError::InvalidTransition {
            target: "Staging",
            ..
        }
    ));

    // Ready.
    authority.mark_ready(&guard).unwrap();
    assert!(matches!(
        staging_err(authority.begin_staging()),
        AuthorityError::InvalidTransition {
            target: "Staging",
            ..
        }
    ));
}

#[test]
fn begin_staging_at_requires_strictly_greater_epoch_after_revoke() {
    let authority = XdsAuthority::standalone();
    drive_to_ready(&authority);
    authority.revoke().expect("revoke");
    assert_eq!(authority.phase(), AuthorityPhase::Revoked { epoch: 1 });

    // Equal or lower requested epoch is rejected: a fencing token must grow.
    assert!(matches!(
        staging_err(authority.begin_staging_at(1)),
        AuthorityError::InvalidTransition {
            target: "Staging",
            ..
        }
    ));

    // Strictly greater is accepted.
    let guard = authority.begin_staging_at(2).expect("staging at 2");
    assert_eq!(guard.epoch(), 2);
    assert_eq!(authority.phase(), AuthorityPhase::Staging { epoch: 2 });
}

#[test]
fn begin_staging_at_zero_from_standby_is_invalid() {
    let authority = XdsAuthority::standalone();
    assert_eq!(
        staging_err(authority.begin_staging_at(0)),
        AuthorityError::InvalidTransition {
            from: AuthorityPhase::Standby,
            target: "Staging",
        }
    );
}

#[test]
fn begin_staging_convenience_increments_epoch_across_revocations() {
    let authority = XdsAuthority::standalone();
    assert_eq!(authority.begin_staging().unwrap().epoch(), 1);
    authority.revoke().unwrap();
    assert_eq!(authority.begin_staging().unwrap().epoch(), 2);
    authority.revoke().unwrap();
    assert_eq!(authority.begin_staging().unwrap().epoch(), 3);
}

#[test]
fn begin_recovery_serving_is_idempotent() {
    let authority = XdsAuthority::standalone();
    let guard = authority.begin_staging().unwrap();
    authority.begin_recovery_serving(&guard).unwrap();
    // Re-entering at the same epoch is a no-op success.
    authority.begin_recovery_serving(&guard).unwrap();
    assert_eq!(
        authority.phase(),
        AuthorityPhase::RecoveryServing { epoch: 1 }
    );
}

#[test]
fn begin_recovery_serving_rejects_a_foreign_guard() {
    let authority = XdsAuthority::standalone();
    let other = XdsAuthority::standalone();
    let foreign = other.begin_staging().unwrap();
    assert!(matches!(
        authority.begin_recovery_serving(&foreign).unwrap_err(),
        AuthorityError::StaleGuard { guard_epoch: 1, .. }
    ));
}

#[test]
fn mark_ready_requires_recovery_serving() {
    let authority = XdsAuthority::standalone();
    let guard = authority.begin_staging().unwrap();
    // Still in Staging; cannot jump to Ready.
    assert!(matches!(
        authority.mark_ready(&guard).unwrap_err(),
        AuthorityError::StaleGuard {
            guard_epoch: 1,
            phase: AuthorityPhase::Staging { epoch: 1 },
        }
    ));
}

#[test]
fn mark_ready_rejects_a_foreign_guard() {
    let authority = XdsAuthority::standalone();
    let guard = authority.begin_staging().unwrap();
    authority.begin_recovery_serving(&guard).unwrap();

    let other = XdsAuthority::standalone();
    let foreign = other.begin_staging().unwrap();
    assert!(matches!(
        authority.mark_ready(&foreign).unwrap_err(),
        AuthorityError::StaleGuard { guard_epoch: 1, .. }
    ));
}

#[test]
fn mark_ready_epoch_is_idempotent_and_fenced() {
    let authority = XdsAuthority::standalone();
    let epoch = drive_to_ready(&authority);

    // Idempotent at the ready epoch.
    authority.mark_ready_epoch(epoch).unwrap();
    assert_eq!(authority.phase(), AuthorityPhase::Ready { epoch });

    // A different epoch cannot mark ready.
    assert!(matches!(
        authority.mark_ready_epoch(epoch + 1).unwrap_err(),
        AuthorityError::StaleGuard { .. }
    ));
}

#[test]
fn revoke_preserves_epoch_and_is_idempotent() {
    let authority = XdsAuthority::standalone();
    let epoch = drive_to_ready(&authority);

    authority.revoke().unwrap();
    assert_eq!(authority.phase(), AuthorityPhase::Revoked { epoch });

    // Second revoke is a no-op success.
    authority.revoke().unwrap();
    assert_eq!(authority.phase(), AuthorityPhase::Revoked { epoch });
}

#[test]
fn revoke_from_standby_is_invalid() {
    let authority = XdsAuthority::standalone();
    assert_eq!(
        authority.revoke().unwrap_err(),
        AuthorityError::InvalidTransition {
            from: AuthorityPhase::Standby,
            target: "Revoked",
        }
    );
}

#[test]
fn mutation_guard_only_available_while_serving() {
    let authority = XdsAuthority::standalone();
    assert!(authority.mutation_guard().is_none()); // Standby

    let guard = authority.begin_staging().unwrap();
    assert!(authority.mutation_guard().is_none()); // Staging

    authority.begin_recovery_serving(&guard).unwrap();
    assert!(authority.mutation_guard().is_some()); // RecoveryServing

    authority.mark_ready(&guard).unwrap();
    assert!(authority.mutation_guard().is_some()); // Ready

    authority.revoke().unwrap();
    assert!(authority.mutation_guard().is_none()); // Revoked
}

#[test]
fn validate_delivery_epoch_matches_only_the_serving_epoch() {
    let authority = XdsAuthority::standalone();
    // Not serving yet.
    assert!(authority.validate_delivery_epoch(1).is_err());

    let epoch = drive_to_ready(&authority);
    assert!(authority.validate_delivery_epoch(epoch).is_ok());
    assert!(matches!(
        authority.validate_delivery_epoch(epoch + 1).unwrap_err(),
        AuthorityError::StaleGuard { guard_epoch, .. } if guard_epoch == epoch + 1
    ));

    // No longer serving after revoke.
    authority.revoke().unwrap();
    assert!(authority.validate_delivery_epoch(epoch).is_err());
}

#[test]
fn recovery_guard_validates_during_staging_and_serving_only() {
    let authority = XdsAuthority::standalone();
    let guard = authority.begin_staging().unwrap();
    assert!(guard.validate().is_ok()); // Staging

    authority.begin_recovery_serving(&guard).unwrap();
    assert!(guard.validate().is_ok()); // RecoveryServing

    // Ready is past the recovery window, so the recovery guard goes stale.
    authority.mark_ready(&guard).unwrap();
    assert!(matches!(
        guard.validate().unwrap_err(),
        AuthorityError::StaleGuard {
            guard_epoch: 1,
            phase: AuthorityPhase::Ready { epoch: 1 },
        }
    ));
}

#[test]
fn superseded_leader_guard_is_fenced_out_after_new_epoch() {
    // The core split-brain defense: a guard held by a superseded leader must
    // stop validating the instant a newer epoch is established.
    let authority = XdsAuthority::standalone();
    drive_to_ready(&authority); // Ready { epoch: 1 }

    let stale = authority.mutation_guard().expect("guard at epoch 1");
    assert_eq!(stale.epoch(), 1);
    assert!(stale.validate().is_ok());

    // Failover begins: revoke immediately fences the old guard.
    authority.revoke().unwrap();
    assert!(matches!(
        stale.validate().unwrap_err(),
        AuthorityError::StaleGuard { guard_epoch: 1, .. }
    ));

    // A new leader takes epoch 2 and serves.
    let fresh = authority.begin_staging_at(2).unwrap();
    authority.begin_recovery_serving(&fresh).unwrap();
    authority.mark_ready(&fresh).unwrap();

    // The old guard stays fenced; only a guard at the live epoch validates.
    assert!(matches!(
        stale.validate().unwrap_err(),
        AuthorityError::StaleGuard { guard_epoch: 1, .. }
    ));
    let live = authority.mutation_guard().expect("guard at epoch 2");
    assert_eq!(live.epoch(), 2);
    assert!(live.validate().is_ok());
    assert!(authority.validate_delivery_epoch(1).is_err());
    assert!(authority.validate_delivery_epoch(2).is_ok());
}

#[test]
fn transitions_are_broadcast_to_subscribers() {
    let authority = XdsAuthority::standalone();
    let mut rx = authority.subscribe();
    assert_eq!(*rx.borrow_and_update(), AuthorityPhase::Standby);

    let guard = authority.begin_staging().unwrap();
    assert!(rx.has_changed().unwrap());
    assert_eq!(
        *rx.borrow_and_update(),
        AuthorityPhase::Staging { epoch: 1 }
    );

    authority.begin_recovery_serving(&guard).unwrap();
    assert_eq!(
        *rx.borrow_and_update(),
        AuthorityPhase::RecoveryServing { epoch: 1 }
    );
}
