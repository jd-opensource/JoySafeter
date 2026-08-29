use crate::ids::SandboxId;

use super::NetworkPolicyGeneration;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkPolicyAction {
    Reconcile,
    Remove,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkPolicyRequest {
    pub sandbox_id: SandboxId,
    pub action: NetworkPolicyAction,
    pub generation: Option<NetworkPolicyGeneration>,
}

impl NetworkPolicyRequest {
    pub fn reconcile(sandbox_id: SandboxId, generation: NetworkPolicyGeneration) -> Self {
        Self {
            sandbox_id,
            action: NetworkPolicyAction::Reconcile,
            generation: Some(generation),
        }
    }

    pub fn remove(sandbox_id: SandboxId) -> Self {
        Self {
            sandbox_id,
            action: NetworkPolicyAction::Remove,
            generation: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use uuid::Uuid;

    #[test]
    fn reconcile_request_carries_exact_generation() {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());
        let generation = NetworkPolicyGeneration {
            policy_hash: "policy-hash".to_string(),
            policy_version: 7,
        };

        let request = NetworkPolicyRequest::reconcile(sandbox_id, generation.clone());

        assert_eq!(request.sandbox_id, sandbox_id);
        assert_eq!(request.action, NetworkPolicyAction::Reconcile);
        assert_eq!(request.generation, Some(generation));
    }

    #[test]
    fn removal_request_has_no_policy_generation() {
        let sandbox_id = SandboxId::from_uuid(Uuid::now_v7());

        let request = NetworkPolicyRequest::remove(sandbox_id);

        assert_eq!(request.action, NetworkPolicyAction::Remove);
        assert_eq!(request.generation, None);
    }
}
