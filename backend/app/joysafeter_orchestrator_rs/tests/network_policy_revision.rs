use joysafeter_orchestrator::kernel::network_policy::envoy_model::SandboxCredentials;
use joysafeter_orchestrator::kernel::network_policy::DesiredNetworkPolicy;

#[test]
fn sandbox_proxy_auth_token_does_not_change_semantic_policy_revision() {
    let without_token = SandboxCredentials::default();
    let with_token = SandboxCredentials::default()
        .with_proxy_auth_token(Some("sandbox-instance-token".to_string()));

    let without_token_revision = DesiredNetworkPolicy::from_inputs(None, &without_token)
        .expect("policy without proxy token")
        .revision();
    let with_token_policy =
        DesiredNetworkPolicy::from_inputs(None, &with_token).expect("policy with proxy token");

    assert_eq!(without_token_revision, with_token_policy.revision());
    assert_eq!(
        with_token_policy
            .render_for(joysafeter_orchestrator::ids::SandboxId::new())
            .proxy_auth_token
            .as_deref(),
        Some("sandbox-instance-token"),
        "the transport token must still be rendered into the sandbox listener",
    );
}
