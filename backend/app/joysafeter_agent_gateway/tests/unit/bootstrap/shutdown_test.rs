use super::*;

#[tokio::test]
async fn signals_created_after_shutdown_also_complete() {
    let shutdown = ShutdownCoordinator::new();
    let before = shutdown.signal();
    shutdown.begin();
    let after = shutdown.signal();

    tokio::time::timeout(std::time::Duration::from_millis(100), before.wait())
        .await
        .expect("existing signal should complete");
    tokio::time::timeout(std::time::Duration::from_millis(100), after.wait())
        .await
        .expect("late signal should complete");
}
