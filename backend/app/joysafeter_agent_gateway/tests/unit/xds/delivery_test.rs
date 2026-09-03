use super::*;

fn request(sandbox_id: SandboxId, version: i64, hash: &str) -> DeliveryRequest {
    DeliveryRequest {
        authority_epoch: 1,
        sandbox_id,
        generation: DeliveryGeneration {
            policy_hash: hash.to_string(),
            policy_version: version,
        },
    }
}

#[test]
fn generation_watermark_rejects_stale_conflicting_and_removed_generation_writes() {
    let sandbox_id = SandboxId::new();
    let mut coordinator = DeliveryCoordinator::default();

    coordinator
        .admit_apply(&request(sandbox_id, 2, "hash-2"))
        .expect("initial generation");
    let attempt = coordinator
        .begin_attempt(
            request(sandbox_id, 2, "hash-2"),
            DeliveryTarget::AnyNode,
            HashSet::from([ResourceType::Listener]),
        )
        .expect("initial attempt");
    assert_eq!(
        coordinator
            .admit_apply(&request(sandbox_id, 2, "hash-2"))
            .expect("identical generation is idempotent"),
        ApplyAdmission::Existing(attempt)
    );
    assert_eq!(
        coordinator
            .admit_apply(&request(sandbox_id, 1, "hash-1"))
            .expect_err("older generation must fail"),
        DeliveryError::StaleGeneration
    );
    assert_eq!(
        coordinator
            .admit_apply(&request(sandbox_id, 2, "different-hash"))
            .expect_err("same version with different content must fail"),
        DeliveryError::ConflictingGeneration
    );
    coordinator.mark_removed(sandbox_id, None);
    assert_eq!(
        coordinator
            .admit_apply(&request(sandbox_id, 2, "hash-2"))
            .expect_err("a removed generation must not be replayed"),
        DeliveryError::RemovedGeneration
    );
    assert_eq!(
        coordinator
            .admit_apply(&request(sandbox_id, 1, "hash-1"))
            .expect_err("a generation older than the tombstone must fail"),
        DeliveryError::StaleGeneration
    );
    assert_eq!(
        coordinator
            .admit_apply(&request(sandbox_id, 3, "hash-3"))
            .expect("a newer lifecycle generation may recreate the policy"),
        ApplyAdmission::New
    );
}

#[test]
fn removing_an_unknown_sandbox_does_not_block_its_initial_policy() {
    let sandbox_id = SandboxId::new();
    let mut coordinator = DeliveryCoordinator::default();

    coordinator.mark_removed(sandbox_id, None);

    assert_eq!(
        coordinator
            .admit_apply(&request(sandbox_id, 1, "hash-1"))
            .expect("an idempotent delete without a known generation must not create a tombstone"),
        ApplyAdmission::New
    );
}

#[test]
fn conditional_remove_cannot_delete_a_newer_generation() {
    let sandbox_id = SandboxId::new();
    let mut coordinator = DeliveryCoordinator::default();

    coordinator
        .admit_apply(&request(sandbox_id, 2, "hash-2"))
        .expect("current generation");

    assert_eq!(
        coordinator
            .admit_remove(
                sandbox_id,
                Some(&DeliveryGeneration {
                    policy_hash: "hash-1".to_string(),
                    policy_version: 1,
                }),
            )
            .expect("stale removal is an idempotent no-op"),
        RemoveAdmission::Superseded
    );
    assert_eq!(
        coordinator
            .admit_remove(
                sandbox_id,
                Some(&DeliveryGeneration {
                    policy_hash: "hash-3".to_string(),
                    policy_version: 3,
                }),
            )
            .expect_err("a future removal must not delete the current generation"),
        DeliveryError::RemovalGenerationAhead
    );
}
