use super::{acquire_step, lease_expired, next_takeover_epoch, observed_expiry_step, AcquireStep};
use crate::xds::authority::AuthorityPhase;
use chrono::{DateTime, Utc};
use k8s_openapi::api::coordination::v1::LeaseSpec;
use k8s_openapi::apimachinery::pkg::apis::meta::v1::MicroTime;
use std::time::{Duration, Instant};

#[test]
fn only_serving_authority_is_an_ads_candidate() {
    assert!(!AuthorityPhase::Standby.serves_ads());
    assert!(AuthorityPhase::RecoveryServing { epoch: 1 }.serves_ads());
    assert!(AuthorityPhase::Ready { epoch: 1 }.serves_ads());
}

#[test]
fn missing_renewal_timestamp_is_treated_as_expired() {
    assert!(lease_expired(None, Duration::from_secs(15), Utc::now()));
}

#[test]
fn lease_is_live_within_its_duration_and_expired_after() {
    let now = Utc::now();
    let duration = Duration::from_secs(15);

    let fresh = MicroTime(now - chrono::Duration::seconds(5));
    assert!(!lease_expired(Some(&fresh), duration, now));

    let stale = MicroTime(now - chrono::Duration::seconds(20));
    assert!(lease_expired(Some(&stale), duration, now));
}

#[test]
fn out_of_range_duration_falls_back_to_fifteen_seconds() {
    let now = Utc::now();
    // Too large for chrono::Duration::from_std, so the 15s fallback applies.
    let duration = Duration::from_secs(u64::MAX);

    let within = MicroTime(now - chrono::Duration::seconds(10));
    assert!(!lease_expired(Some(&within), duration, now));

    let beyond = MicroTime(now - chrono::Duration::seconds(20));
    assert!(lease_expired(Some(&beyond), duration, now));
}

#[test]
fn takeover_epoch_starts_at_one_and_increments_monotonically() {
    assert_eq!(next_takeover_epoch(None), 1);
    assert_eq!(next_takeover_epoch(Some(0)), 1);
    assert_eq!(next_takeover_epoch(Some(1)), 2);
    assert_eq!(next_takeover_epoch(Some(41)), 42);
}

#[test]
fn takeover_epoch_is_at_least_one_for_bogus_transition_counts() {
    assert_eq!(next_takeover_epoch(Some(-5)), 1);
    assert_eq!(next_takeover_epoch(Some(i32::MIN)), 1);
}

#[test]
fn takeover_epoch_saturates_instead_of_overflowing() {
    assert_eq!(next_takeover_epoch(Some(i32::MAX)), i32::MAX);
}

fn lease_spec(
    holder: Option<&str>,
    renewed_secs_ago: Option<i64>,
    now: DateTime<Utc>,
) -> LeaseSpec {
    LeaseSpec {
        holder_identity: holder.map(|value| value.to_string()),
        renew_time: renewed_secs_ago.map(|secs| MicroTime(now - chrono::Duration::seconds(secs))),
        ..Default::default()
    }
}

#[test]
fn acquire_reacquires_a_self_held_lease_for_a_fresh_local_term() {
    let now = Utc::now();
    let spec = lease_spec(Some("me"), Some(1), now);
    assert_eq!(
        acquire_step(&spec, "me", Duration::from_secs(15), now),
        AcquireStep::Reacquire
    );
}

#[test]
fn self_held_lease_reacquisition_advances_the_fencing_epoch() {
    let now = Utc::now();
    let mut spec = lease_spec(Some("me"), Some(1), now);
    spec.lease_transitions = Some(7);

    assert_eq!(
        acquire_step(&spec, "me", Duration::from_secs(15), now),
        AcquireStep::Reacquire
    );
    assert_eq!(next_takeover_epoch(spec.lease_transitions), 8);
}

#[test]
fn acquire_yields_to_a_live_lease_held_by_another_identity() {
    let now = Utc::now();
    let spec = lease_spec(Some("other"), Some(1), now);
    assert_eq!(
        acquire_step(&spec, "me", Duration::from_secs(15), now),
        AcquireStep::Yield
    );
}

#[test]
fn acquire_takes_over_an_expired_lease_from_another_identity() {
    let now = Utc::now();
    let spec = lease_spec(Some("other"), Some(20), now);
    assert_eq!(
        acquire_step(&spec, "me", Duration::from_secs(15), now),
        AcquireStep::Takeover
    );
}

#[test]
fn acquire_takes_over_an_unheld_lease() {
    let now = Utc::now();
    // Neither an absent holder nor an empty-string holder is a live owner.
    for holder in [None, Some("")] {
        let spec = lease_spec(holder, Some(1), now);
        assert_eq!(
            acquire_step(&spec, "me", Duration::from_secs(15), now),
            AcquireStep::Takeover
        );
    }
}

#[test]
fn acquire_takes_over_when_a_foreign_holder_never_renewed() {
    let now = Utc::now();
    let spec = lease_spec(Some("other"), None, now);
    assert_eq!(
        acquire_step(&spec, "me", Duration::from_secs(15), now),
        AcquireStep::Takeover
    );
}

// ── Observed-time liveness (Bug 2: clock-skew-immune expiry) ────────────────────

#[test]
fn observed_expiry_treats_missing_renew_time_as_expired() {
    let mut state = Some((MicroTime(Utc::now()), Instant::now()));
    assert!(observed_expiry_step(
        &mut state,
        None,
        Instant::now(),
        Duration::from_secs(15)
    ));
    // Observation is cleared so a later appearance restarts the window.
    assert!(state.is_none());
}

#[test]
fn observed_expiry_resets_window_when_renew_time_advances() {
    let base = Instant::now();
    let mut state = None;
    let first = MicroTime(Utc::now());
    // First sighting of a foreign holder: never immediately expired.
    assert!(!observed_expiry_step(
        &mut state,
        Some(&first),
        base,
        Duration::from_secs(15)
    ));
    // Holder renews (renewTime advances) right before the window would elapse;
    // liveness must reset regardless of how the wall-clock values compare.
    let second = MicroTime(Utc::now() + chrono::Duration::seconds(1));
    let later = base + Duration::from_secs(14);
    assert!(!observed_expiry_step(
        &mut state,
        Some(&second),
        later,
        Duration::from_secs(15)
    ));
    // Only sustained non-renewal past the window (measured locally) expires it.
    let much_later = later + Duration::from_secs(16);
    assert!(observed_expiry_step(
        &mut state,
        Some(&second),
        much_later,
        Duration::from_secs(15)
    ));
}

#[test]
fn observed_expiry_is_measured_from_local_time_not_holder_clock() {
    // A holder whose renewTime is wildly in the future (skewed clock) is still
    // judged live only for lease_duration of *local* time after we first saw it.
    let base = Instant::now();
    let mut state = None;
    let skewed = MicroTime(Utc::now() + chrono::Duration::hours(1));
    assert!(!observed_expiry_step(
        &mut state,
        Some(&skewed),
        base,
        Duration::from_secs(15)
    ));
    // Same (unchanged) renewTime, local window elapsed → expired despite the
    // holder's future-dated wall clock.
    assert!(observed_expiry_step(
        &mut state,
        Some(&skewed),
        base + Duration::from_secs(15),
        Duration::from_secs(15)
    ));
}
