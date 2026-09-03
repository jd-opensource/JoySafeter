use super::*;

#[test]
fn socket_cleanup_plan_uses_a_validated_sandbox_uuid_and_fixed_arguments() {
    let plan = socket_cleanup_plan("joysafeter-01a05121-bff9-7b30-b70a-3b8916454456")
        .expect("valid managed sandbox pod name");

    assert_eq!(
        plan,
        vec![
            "rm".to_string(),
            "-rf".to_string(),
            "--".to_string(),
            "/sockets/01a05121-bff9-7b30-b70a-3b8916454456".to_string(),
        ]
    );
}

#[test]
fn socket_cleanup_plan_rejects_non_sandbox_external_ids() {
    let error = socket_cleanup_plan("joysafeter-envoy-xddjx")
        .expect_err("non-sandbox pod names must not become filesystem paths");

    assert!(error.to_string().contains("invalid K8s sandbox pod name"));
}

#[test]
fn pod_placement_applies_selector_and_tolerations_to_dynamic_sandbox() {
    let mut pod_spec = json!({"containers": []});
    let node_selector = BTreeMap::from([(
        "joysafeter.io/node-pool".to_string(),
        "production".to_string(),
    )]);
    let tolerations = vec![json!({
        "key": "joysafeter.io/dedicated",
        "operator": "Equal",
        "value": "production",
        "effect": "NoSchedule"
    })];

    apply_pod_placement(
        &mut pod_spec,
        Some("joysafeter-production"),
        &node_selector,
        &tolerations,
    );

    assert_eq!(pod_spec["priorityClassName"], "joysafeter-production");
    assert_eq!(
        pod_spec["nodeSelector"]["joysafeter.io/node-pool"],
        "production"
    );
    assert_eq!(pod_spec["tolerations"], json!(tolerations));
}
