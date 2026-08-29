use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    fs::read_to_string(PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path))
        .expect("read source file")
}

#[test]
fn renderer_implementations_are_isolated_from_runtime_and_transport() {
    for path in [
        "src/sandbox/envoy_render/json.rs",
        "src/sandbox/envoy_render/proto.rs",
    ] {
        let module = source(path);
        for forbidden in [
            "tokio::",
            "sqlx::",
            "redis::",
            "bollard::",
            "kube::",
            "tonic::",
            "DeltaXdsServer",
            "SandboxProvider",
            "LdsBackend",
            "CdsBackend",
        ] {
            assert!(
                !module.contains(forbidden),
                "{path} contains forbidden dependency: {forbidden}"
            );
        }
    }
}

#[test]
fn policy_models_are_owned_by_network_policy_and_renderer_only_consumes_them() {
    for path in [
        "src/kernel/network_policy.rs",
        "src/kernel/mcp_runtime_plan.rs",
    ] {
        let module = source(path);
        assert!(
            module.contains("network_policy::envoy_model") || path.ends_with("network_policy.rs")
        );
        assert!(!module.contains("sandbox::envoy_render"));
        assert!(!module.contains("sandbox::lds_backend"));
    }

    assert!(!std::path::Path::new("src/sandbox/envoy_render/model.rs").exists());
    for path in [
        "src/sandbox/envoy_render/json.rs",
        "src/sandbox/envoy_render/proto.rs",
    ] {
        assert!(source(path).contains("kernel::network_policy::envoy_model"));
    }

    let provider = source("src/sandbox/provider.rs");
    assert!(!provider.contains("sandbox::envoy_render"));
    assert!(!provider.contains("sandbox::lds_backend"));
}
