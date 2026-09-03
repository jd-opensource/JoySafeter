use super::classify_failure_status;
use crate::db::queries::NetworkPolicyFailureStatus;
use crate::kernel::network_policy::ports::NetworkPolicyApplyError;

#[test]
fn only_an_explicit_envoy_nack_is_classified_as_nacked() {
    let nack = anyhow::Error::new(NetworkPolicyApplyError::Nacked(anyhow::anyhow!(
        "listener rejected"
    )));
    assert_eq!(
        classify_failure_status(&nack),
        NetworkPolicyFailureStatus::Nacked
    );

    let timeout = anyhow::anyhow!("refresh_networking exceeded 30s");
    assert_eq!(
        classify_failure_status(&timeout),
        NetworkPolicyFailureStatus::Failed
    );
}
