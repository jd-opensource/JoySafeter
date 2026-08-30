use std::sync::Arc;

use tokio::sync::Semaphore;

use crate::kernel::harness_input_builder::HarnessInputBuilder;

use super::cleanup::RunnerCleanupService;
use super::execution::RunnerExecutionService;
use super::recovery::RunnerRecoveryService;

/// Process-lifetime Runner capabilities assembled by the bootstrap composition root.
pub(crate) struct RunnerFlowSet {
    execution: RunnerExecutionService,
    recovery: RunnerRecoveryService,
    cleanup: RunnerCleanupService,
    harness_input_builder: HarnessInputBuilder,
}

impl RunnerFlowSet {
    pub(crate) fn new(
        execution: RunnerExecutionService,
        recovery: RunnerRecoveryService,
        cleanup: RunnerCleanupService,
        harness_input_builder: HarnessInputBuilder,
    ) -> Self {
        Self {
            execution,
            recovery,
            cleanup,
            harness_input_builder,
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

    pub(crate) fn harness_input_builder(&self) -> HarnessInputBuilder {
        self.harness_input_builder.clone()
    }
}
