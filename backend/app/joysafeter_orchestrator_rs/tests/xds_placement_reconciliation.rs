use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("read source file")
}

#[test]
fn pod_watcher_only_emits_neutral_placement_events() {
    let watcher = source("src/sandbox/pod_watcher.rs");
    assert!(watcher.contains("PlacementEventSink"));
    assert!(!watcher.contains("PlacementEventHandler"));
    assert!(!watcher.contains("XdsControlPlane"));
}

#[test]
fn bootstrap_does_not_apply_ownership_inside_provider_callbacks() {
    let factories = source("src/bootstrap/runtime_factories.rs");
    assert!(factories.contains("PlacementReconciler"));
    assert!(!factories.contains("fn placement_handler"));
    assert!(!factories.contains("assign_sandbox_node"));
    assert!(!factories.contains("replace_node_assignments"));
}

#[test]
fn placement_reconciler_is_supervised_as_degradable() {
    let application = source("src/bootstrap/application.rs");
    assert!(application.contains("placement-reconciler"));
    assert!(application.contains("ServiceCriticality::Degradable"));
}
