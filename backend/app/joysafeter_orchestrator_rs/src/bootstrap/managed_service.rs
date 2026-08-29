use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use tokio::sync::mpsc;
use tokio::task::{AbortHandle, JoinHandle};
use tracing::warn;

const MAX_MANAGED_SERVICES: usize = 128;

#[derive(Clone, Default)]
pub(crate) struct ReadinessGate {
    ready: Arc<AtomicBool>,
}

impl ReadinessGate {
    pub(crate) fn new() -> Self {
        Self::default()
    }

    pub(crate) fn is_ready(&self) -> bool {
        self.ready.load(Ordering::Acquire)
    }

    pub(crate) fn mark_ready(&self) {
        self.ready.store(true, Ordering::Release);
    }

    pub(crate) fn mark_not_ready(&self) {
        self.ready.store(false, Ordering::Release);
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ServiceCriticality {
    Critical,
    Degradable,
    BestEffort,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ServiceHealth {
    Starting,
    Ready,
    Exited,
}

struct ServiceState {
    criticality: ServiceCriticality,
    health: ServiceHealth,
}

#[derive(Default)]
struct SupervisorState {
    startup_sealed: bool,
    services: HashMap<String, ServiceState>,
}

struct SharedSupervisorState {
    readiness: ReadinessGate,
    state: Mutex<SupervisorState>,
}

impl SharedSupervisorState {
    fn update_readiness(&self, state: &SupervisorState) {
        let all_critical_ready = state.services.values().all(|service| {
            service.criticality != ServiceCriticality::Critical
                || service.health == ServiceHealth::Ready
        });
        if state.startup_sealed && all_critical_ready {
            self.readiness.mark_ready();
        } else {
            self.readiness.mark_not_ready();
        }
    }
}

#[derive(Clone)]
pub(crate) struct ManagedServiceHandle {
    service_name: String,
    shared: Arc<SharedSupervisorState>,
}

impl ManagedServiceHandle {
    pub(crate) fn mark_ready(&self) {
        let mut state = self.shared.state.lock().expect("supervisor state poisoned");
        let Some(service) = state.services.get_mut(&self.service_name) else {
            return;
        };
        if service.health == ServiceHealth::Starting {
            service.health = ServiceHealth::Ready;
        }
        self.shared.update_readiness(&state);
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ServiceExit {
    service_name: String,
    error: Option<String>,
}

impl ServiceExit {
    pub(crate) fn service_name(&self) -> &str {
        &self.service_name
    }

    pub(crate) fn error(&self) -> Option<&str> {
        self.error.as_deref()
    }
}

pub(crate) struct TaskSupervisor {
    shared: Arc<SharedSupervisorState>,
    critical_exit_tx: mpsc::Sender<ServiceExit>,
    critical_exit_rx: mpsc::Receiver<ServiceExit>,
    abort_handles: Vec<(String, AbortHandle)>,
    monitor_handles: Vec<JoinHandle<()>>,
}

impl TaskSupervisor {
    pub(crate) fn new(readiness: ReadinessGate) -> Self {
        let (critical_exit_tx, critical_exit_rx) = mpsc::channel(1);
        Self {
            shared: Arc::new(SharedSupervisorState {
                readiness,
                state: Mutex::new(SupervisorState::default()),
            }),
            critical_exit_tx,
            critical_exit_rx,
            abort_handles: Vec::new(),
            monitor_handles: Vec::new(),
        }
    }

    pub(crate) fn register(
        &mut self,
        service_name: impl Into<String>,
        criticality: ServiceCriticality,
        handle: JoinHandle<()>,
    ) -> anyhow::Result<ManagedServiceHandle> {
        let service_name = service_name.into();
        {
            let mut state = self.shared.state.lock().expect("supervisor state poisoned");
            if state.startup_sealed {
                handle.abort();
                anyhow::bail!("managed service registration is sealed: {service_name}");
            }
            if state.services.contains_key(&service_name) {
                handle.abort();
                anyhow::bail!("managed service already registered: {service_name}");
            }
            if state.services.len() >= MAX_MANAGED_SERVICES {
                handle.abort();
                anyhow::bail!("managed service limit exceeded: {MAX_MANAGED_SERVICES}");
            }
            state.services.insert(
                service_name.clone(),
                ServiceState {
                    criticality,
                    health: ServiceHealth::Starting,
                },
            );
            self.shared.update_readiness(&state);
        }
        self.abort_handles
            .push((service_name.clone(), handle.abort_handle()));
        let shared = self.shared.clone();
        let critical_exit_tx = self.critical_exit_tx.clone();
        let managed_handle = ManagedServiceHandle {
            service_name: service_name.clone(),
            shared: self.shared.clone(),
        };
        self.monitor_handles.push(tokio::spawn(async move {
            let error = match handle.await {
                Ok(()) => None,
                Err(error) if error.is_cancelled() => return,
                Err(error) => Some(error.to_string()),
            };
            {
                let mut state = shared.state.lock().expect("supervisor state poisoned");
                if let Some(service) = state.services.get_mut(&service_name) {
                    service.health = ServiceHealth::Exited;
                }
                shared.update_readiness(&state);
            }
            let exit = ServiceExit {
                service_name,
                error,
            };
            match criticality {
                ServiceCriticality::Critical => {
                    let _ = critical_exit_tx.try_send(exit);
                }
                ServiceCriticality::Degradable | ServiceCriticality::BestEffort => {
                    warn!(
                        service = %exit.service_name,
                        error = ?exit.error,
                        ?criticality,
                        "non-critical background service exited"
                    );
                }
            }
        }));
        Ok(managed_handle)
    }

    pub(crate) fn seal_startup(&mut self) {
        let mut state = self.shared.state.lock().expect("supervisor state poisoned");
        state.startup_sealed = true;
        self.shared.update_readiness(&state);
    }

    #[cfg(test)]
    pub(crate) fn service_health(&self, service_name: &str) -> Option<ServiceHealth> {
        self.shared
            .state
            .lock()
            .expect("supervisor state poisoned")
            .services
            .get(service_name)
            .map(|service| service.health)
    }

    pub(crate) async fn wait_for_critical_exit(&mut self) -> ServiceExit {
        self.critical_exit_rx
            .recv()
            .await
            .expect("task supervisor critical exit channel closed")
    }

    pub(crate) fn abort(&self, service_name: &str) -> bool {
        let Some((_, handle)) = self
            .abort_handles
            .iter()
            .find(|(name, _)| name == service_name)
        else {
            return false;
        };
        handle.abort();
        true
    }

    pub(crate) async fn shutdown(mut self) {
        self.shared.readiness.mark_not_ready();
        for (_, handle) in &self.abort_handles {
            handle.abort();
        }
        for handle in self.monitor_handles.drain(..) {
            let _ = handle.await;
        }
    }
}

impl Drop for TaskSupervisor {
    fn drop(&mut self) {
        for (_, handle) in &self.abort_handles {
            handle.abort();
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::{ReadinessGate, ServiceCriticality, ServiceHealth, TaskSupervisor};

    #[tokio::test]
    async fn readiness_opens_only_after_all_critical_services_are_ready_and_startup_is_sealed() {
        let readiness = ReadinessGate::new();
        let mut supervisor = TaskSupervisor::new(readiness.clone());
        let grpc = supervisor
            .register(
                "runner-grpc",
                ServiceCriticality::Critical,
                tokio::spawn(std::future::pending()),
            )
            .expect("register runner gRPC");
        let scheduler = supervisor
            .register(
                "task-scheduler",
                ServiceCriticality::Critical,
                tokio::spawn(std::future::pending()),
            )
            .expect("register scheduler");

        grpc.mark_ready();
        assert!(!readiness.is_ready());

        supervisor.seal_startup();
        assert!(!readiness.is_ready());

        scheduler.mark_ready();
        assert!(readiness.is_ready());
        assert_eq!(
            supervisor.service_health("runner-grpc"),
            Some(ServiceHealth::Ready)
        );

        supervisor.shutdown().await;
    }

    #[tokio::test]
    async fn best_effort_service_does_not_gate_readiness_or_fail_the_application() {
        let readiness = ReadinessGate::new();
        let mut supervisor = TaskSupervisor::new(readiness.clone());
        supervisor
            .register(
                "metrics-flush",
                ServiceCriticality::BestEffort,
                tokio::spawn(async {}),
            )
            .expect("register metrics flush");

        supervisor.seal_startup();
        tokio::time::sleep(Duration::from_millis(20)).await;

        assert!(readiness.is_ready());
        assert!(tokio::time::timeout(
            Duration::from_millis(20),
            supervisor.wait_for_critical_exit(),
        )
        .await
        .is_err());
    }

    #[tokio::test]
    async fn duplicate_and_late_service_registration_are_rejected() {
        let readiness = ReadinessGate::new();
        let mut supervisor = TaskSupervisor::new(readiness);
        supervisor
            .register(
                "runner-grpc",
                ServiceCriticality::Critical,
                tokio::spawn(std::future::pending()),
            )
            .expect("register runner gRPC");

        let duplicate = supervisor.register(
            "runner-grpc",
            ServiceCriticality::Critical,
            tokio::spawn(std::future::pending()),
        );
        assert!(duplicate.is_err());

        supervisor.seal_startup();
        let late = supervisor.register(
            "late-service",
            ServiceCriticality::Critical,
            tokio::spawn(std::future::pending()),
        );
        assert!(late.is_err());

        supervisor.shutdown().await;
    }
}
