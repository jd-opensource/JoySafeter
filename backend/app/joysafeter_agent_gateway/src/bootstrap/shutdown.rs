//! Process-wide graceful shutdown coordination for network listeners.

use tokio::sync::watch;

#[derive(Clone)]
pub struct ShutdownCoordinator {
    requested: watch::Sender<bool>,
}

impl ShutdownCoordinator {
    pub fn new() -> Self {
        let (requested, _receiver) = watch::channel(false);
        Self { requested }
    }

    pub fn signal(&self) -> ShutdownSignal {
        ShutdownSignal {
            requested: self.requested.subscribe(),
        }
    }

    pub fn begin(&self) {
        self.requested.send_replace(true);
    }
}

impl Default for ShutdownCoordinator {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Clone)]
pub struct ShutdownSignal {
    requested: watch::Receiver<bool>,
}

impl ShutdownSignal {
    pub async fn wait(mut self) {
        while !*self.requested.borrow_and_update() {
            if self.requested.changed().await.is_err() {
                return;
            }
        }
    }
}

#[cfg(test)]
#[path = "../../tests/unit/bootstrap/shutdown_test.rs"]
mod tests;
