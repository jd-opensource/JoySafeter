use std::sync::Arc;

use tokio::sync::Semaphore;

use crate::kernel::harness_input_builder::HarnessInputBuilder;

use super::admission::RunnerAdmissionService;
use super::cleanup::RunnerCleanupService;
use super::execution::RunnerExecutionService;
use super::failure::RunnerFailureService;
use super::metrics::RunnerMetrics;
use super::recovery::RunnerRecoveryService;

/// Process-lifetime Runner capabilities assembled by the bootstrap composition root.
pub(crate) struct RunnerFlowSet {
    admission: RunnerAdmissionService,
    execution: RunnerExecutionService,
    recovery: RunnerRecoveryService,
    cleanup: RunnerCleanupService,
    failure: RunnerFailureService,
    harness_input_builder: HarnessInputBuilder,
    metrics: RunnerMetrics,
}

impl RunnerFlowSet {
    pub(crate) fn new(
        admission: RunnerAdmissionService,
        execution: RunnerExecutionService,
        recovery: RunnerRecoveryService,
        cleanup: RunnerCleanupService,
        failure: RunnerFailureService,
        harness_input_builder: HarnessInputBuilder,
    ) -> Self {
        Self {
            admission,
            execution,
            recovery,
            cleanup,
            failure,
            harness_input_builder,
            metrics: RunnerMetrics::default(),
        }
    }

    pub(crate) fn admission(&self) -> RunnerAdmissionService {
        self.admission.clone()
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

    pub(crate) fn failure(&self) -> RunnerFailureService {
        self.failure.clone()
    }

    pub(crate) fn harness_input_builder(&self) -> HarnessInputBuilder {
        self.harness_input_builder.clone()
    }

    pub(crate) fn metrics(&self) -> RunnerMetrics {
        self.metrics.clone()
    }
}
