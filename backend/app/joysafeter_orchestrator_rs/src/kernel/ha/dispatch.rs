//! Shared dispatch logic for sending commands to a local `SandboxBridge`.
//!
//! Both `LocalTaskDispatcher` and `RedisTaskDispatcher` need to send commands
//! to a local bridge. This module provides the common implementation to avoid
//! duplicating proto message construction.

use std::sync::Arc;

use anyhow::anyhow;

use crate::grpc::proto::{self, orchestrator_message, OrchestratorMessage};
use crate::ids::SandboxId;
use crate::kernel::sandbox_bridge::SandboxBridge;

use super::traits::DispatchCommand;

/// Dispatch a command to a local bridge. This is the shared implementation
/// used by both `LocalTaskDispatcher` and `RedisTaskDispatcher`.
pub async fn dispatch_to_bridge(
    bridge: &Arc<SandboxBridge>,
    sandbox_id: SandboxId,
    command: &DispatchCommand,
) -> anyhow::Result<()> {
    match command {
        DispatchCommand::Cancel { reason } => {
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Cancel(proto::CancelTask {
                    reason: reason.clone(),
                })),
            };
            bridge
                .send_to_runner(msg)
                .await
                .map_err(|e| anyhow!("failed to send cancel to sandbox {sandbox_id}: {e}"))?;
            bridge.request_cancel().await;
        }
        DispatchCommand::SendInput { content } => {
            bridge
                .send_control_input(content.clone())
                .await
                .map_err(|e| anyhow!("failed to send input to sandbox {sandbox_id}: {e}"))?;
        }
        DispatchCommand::Shutdown { reason } => {
            let msg = OrchestratorMessage {
                payload: Some(orchestrator_message::Payload::Shutdown(proto::Shutdown {
                    reason: reason.clone(),
                })),
            };
            bridge
                .send_to_runner(msg)
                .await
                .map_err(|e| anyhow!("failed to send shutdown to sandbox {sandbox_id}: {e}"))?;
        }
        DispatchCommand::TaskWakeup => {
            bridge.task_available.notify_one();
        }
    }
    Ok(())
}
