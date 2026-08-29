use std::sync::Arc;

use tokio::sync::Semaphore;

use super::cleanup::RunnerCleanupService;
use super::execution::RunnerExecutionService;
use super::recovery::RunnerRecoveryService;

/// Process-lifetime Runner capabilities assembled by the bootstrap composition root.
pub(crate) struct RunnerFlowSet {
    execution: RunnerExecutionService,
    recovery: RunnerRecoveryService,
    cleanup: RunnerCleanupService,
}

impl RunnerFlowSet {
    pub(crate) fn new(
        execution: RunnerExecutionService,
        recovery: RunnerRecoveryService,
        cleanup: RunnerCleanupService,
    ) -> Self {
        Self {
            execution,
            recovery,
            cleanup,
        }
    }

    pub(crate) fn execution_semaphore(&self) -> Arc<Semaphore> {
        self.execution.semaphore()
    }

    pub(crate) fn recovery(&self) -> RunnerRecoveryService {
        self.recovery.clone()
    }

    pub(crate) fn cleanup(&self) -> RunnerCleanupService {
        self.cleanup.clone()
    }
}
