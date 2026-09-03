use std::collections::HashSet;

use super::{
    AttemptState, DeliveryError, DeliveryKey, DeliveryOutcome, DeliveryTracker, ReceiptOutcome,
    ResponseReceipt,
};
use crate::ids::SandboxId;
use crate::xds::model::ResourceType;

impl DeliveryTracker {
    pub fn begin_attempt(
        &mut self,
        key: DeliveryKey,
        required_types: HashSet<ResourceType>,
    ) -> Result<(), DeliveryError> {
        validate_key(&key)?;
        if required_types.is_empty() {
            return Err(DeliveryError::EmptyQuorum);
        }
        self.remove_receipts_for_sandbox(key.sandbox_id);
        self.attempts.insert(
            key.sandbox_id,
            AttemptState {
                key,
                required_types,
                acknowledged_types: HashSet::new(),
                outcome: DeliveryOutcome::Pending,
            },
        );
        Ok(())
    }

    pub fn record_response(
        &mut self,
        receipt: ResponseReceipt,
    ) -> Result<ReceiptOutcome, DeliveryError> {
        validate_receipt(&receipt)?;
        let Some(attempt) = self.attempts.get(&receipt.key.sandbox_id) else {
            return Ok(ReceiptOutcome::Stale);
        };
        if attempt.key != receipt.key {
            return Ok(ReceiptOutcome::Stale);
        }
        if !attempt.required_types.contains(&receipt.resource_type) {
            return Err(DeliveryError::UnexpectedResourceType);
        }

        let receipts = self.receipts.entry(receipt.nonce.clone()).or_default();
        if let Some(existing) = receipts.iter().find(|existing| {
            existing.key == receipt.key && existing.resource_type == receipt.resource_type
        }) {
            return if existing == &receipt {
                Ok(ReceiptOutcome::Duplicate)
            } else {
                Err(DeliveryError::ConflictingNonce)
            };
        }
        receipts.push(receipt);
        Ok(ReceiptOutcome::Accepted)
    }

    pub fn acknowledge(&mut self, nonce: &str) -> ReceiptOutcome {
        self.record_outcome(nonce, None)
    }

    pub fn reject(&mut self, nonce: &str, reason: impl Into<String>) -> ReceiptOutcome {
        self.record_outcome(nonce, Some(reason.into()))
    }

    pub fn outcome(&self, key: &DeliveryKey) -> Option<DeliveryOutcome> {
        self.attempts
            .get(&key.sandbox_id)
            .filter(|attempt| attempt.key == *key)
            .map(|attempt| attempt.outcome.clone())
    }

    pub fn current_key(&self, sandbox_id: SandboxId) -> Option<DeliveryKey> {
        self.attempts
            .get(&sandbox_id)
            .map(|attempt| attempt.key.clone())
    }

    pub fn forget(&mut self, sandbox_id: SandboxId) {
        self.attempts.remove(&sandbox_id);
        self.remove_receipts_for_sandbox(sandbox_id);
    }

    fn record_outcome(&mut self, nonce: &str, nack: Option<String>) -> ReceiptOutcome {
        let Some(receipts) = self.receipts.get(nonce).cloned() else {
            return ReceiptOutcome::Stale;
        };
        let mut accepted = false;
        let mut completed = false;

        for receipt in receipts {
            let Some(attempt) = self.attempts.get_mut(&receipt.key.sandbox_id) else {
                continue;
            };
            if attempt.key != receipt.key {
                continue;
            }
            if attempt.outcome != DeliveryOutcome::Pending {
                continue;
            }
            accepted = true;
            if let Some(reason) = &nack {
                attempt.outcome = DeliveryOutcome::Nacked {
                    resource_type: receipt.resource_type,
                    reason: reason.clone(),
                };
                completed = true;
                continue;
            }
            attempt.acknowledged_types.insert(receipt.resource_type);
            if attempt
                .required_types
                .is_subset(&attempt.acknowledged_types)
            {
                attempt.outcome = DeliveryOutcome::Acked;
                completed = true;
            }
        }

        if completed {
            ReceiptOutcome::Completed
        } else if accepted {
            ReceiptOutcome::Accepted
        } else if self.receipts.contains_key(nonce) {
            ReceiptOutcome::Duplicate
        } else {
            ReceiptOutcome::Stale
        }
    }

    fn remove_receipts_for_sandbox(&mut self, sandbox_id: SandboxId) {
        self.receipts.retain(|_, receipts| {
            receipts.retain(|receipt| receipt.key.sandbox_id != sandbox_id);
            !receipts.is_empty()
        });
    }
}

fn validate_key(key: &DeliveryKey) -> Result<(), DeliveryError> {
    if key.authority_epoch == 0 {
        return Err(DeliveryError::InvalidAuthorityEpoch);
    }
    if key.generation.policy_hash.is_empty() || key.generation.policy_version <= 0 {
        return Err(DeliveryError::InvalidGeneration);
    }
    if key.owner_node.trim().is_empty() {
        return Err(DeliveryError::MissingOwnerNode);
    }
    if key.node_session.as_u64() == 0 {
        return Err(DeliveryError::InvalidNodeSession);
    }
    if key.attempt_id.as_u64() == 0 {
        return Err(DeliveryError::InvalidAttemptId);
    }
    Ok(())
}

fn validate_receipt(receipt: &ResponseReceipt) -> Result<(), DeliveryError> {
    validate_key(&receipt.key)?;
    if receipt.nonce.is_empty() {
        return Err(DeliveryError::MissingNonce);
    }
    if receipt.transmitted_names.is_empty() && receipt.removed_names.is_empty() {
        return Err(DeliveryError::EmptyReceipt);
    }
    let mut names = HashSet::new();
    if receipt
        .transmitted_names
        .iter()
        .chain(&receipt.removed_names)
        .any(|name| !names.insert(name))
    {
        return Err(DeliveryError::DuplicateResourceName);
    }
    Ok(())
}
