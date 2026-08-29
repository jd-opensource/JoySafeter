use std::fs;
use std::path::PathBuf;

fn source(path: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(path);
    fs::read_to_string(path).expect("read source file")
}

fn repository_source(path: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .join(path);
    fs::read_to_string(path).expect("read repository source file")
}

fn manifest_document<'a>(source: &'a str, kind: &str, resource_name: &str) -> &'a str {
    source
        .split("\n---\n")
        .find(|document| {
            document.contains(&format!("\nkind: {kind}\n"))
                && document.contains(&format!("metadata:\n  name: {resource_name}"))
        })
        .unwrap_or_else(|| panic!("missing manifest resource {kind}/{resource_name}"))
}

#[test]
fn runner_server_does_not_register_ads() {
    let runner_server = source("src/grpc/server.rs");
    assert!(!runner_server.contains("AggregatedDiscoveryServiceServer"));
    assert!(!runner_server.contains("DeltaXdsServer"));
}

#[test]
fn ads_has_a_dedicated_server_module() {
    let ads_server = source("src/xds/server.rs");
    assert!(ads_server.contains("pub async fn start_ads_server"));
    assert!(!ads_server.contains("sandbox::lds_backend"));

    let registry = source("src/bootstrap/registry.rs");
    assert!(registry.contains("xds::transport"));
    let leader = source("src/xds/leader.rs");
    assert!(leader.contains("super::transport"));
    for (path, module) in [
        ("src/bootstrap/registry.rs", registry),
        ("src/xds/leader.rs", leader),
    ] {
        assert!(
            !module.contains("sandbox::lds_backend"),
            "{path} must not depend on sandbox's compatibility facade"
        );
    }
}

#[test]
fn authority_runtime_and_leader_coordination_live_under_xds() {
    assert!(source("src/xds/authority.rs").contains("pub struct XdsAuthorityState"));
    assert!(source("src/xds/leader.rs").contains("pub struct XdsLeaderHandle"));
    assert!(!PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("src/kernel/xds_authority.rs")
        .exists());
    assert!(!PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("src/kernel/xds_leader.rs")
        .exists());
}

#[test]
fn xds_transport_owns_the_ads_implementation() {
    let transport = source("src/xds/transport.rs");
    assert!(transport.contains("pub struct DeltaXdsServer"));
    assert!(transport.contains("impl AggregatedDiscoveryService for DeltaXdsServer"));
    assert!(!transport.contains("pub use crate::sandbox::lds_backend"));
    assert!(!transport.contains("pub use crate::sandbox::envoy_render"));
    for forbidden in [
        "pub struct GrpcLds",
        "pub struct GrpcCds",
        "impl LdsBackend",
        "impl CdsBackend",
        "FilesystemLds",
        "FilesystemCds",
        "write_config_file",
    ] {
        assert!(
            !transport.contains(forbidden),
            "xDS transport owns forbidden publisher/delivery concern: {forbidden}"
        );
    }

    let publisher = source("src/xds/publisher.rs");
    assert!(publisher.contains("pub struct GrpcLds"));
    assert!(publisher.contains("pub struct GrpcCds"));

    let delivery = source("src/sandbox/envoy_delivery.rs");
    assert!(delivery.contains("pub struct FilesystemLds"));
    assert!(delivery.contains("pub struct FilesystemCds"));

    let sandbox_mod = source("src/sandbox/mod.rs");
    assert!(!sandbox_mod.contains("mod lds_backend"));
    assert!(!PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("src/sandbox/lds_backend.rs")
        .exists());
}

#[test]
fn deployment_routes_ads_to_a_dedicated_port_with_credentials() {
    let service = repository_source("deploy/helm/joysafeter-orchestrator/templates/service.yaml");
    assert!(service.contains("targetPort: xds"));

    let deployment =
        repository_source("deploy/helm/joysafeter-orchestrator/templates/deployment.yaml");
    assert!(deployment.contains("name: xds"));

    let configmap =
        repository_source("deploy/helm/joysafeter-orchestrator/templates/configmap.yaml");
    assert!(configmap.contains("JOYSAFETER_XDS_PORT"));
    assert!(configmap.contains(".Values.orchestrator.xds.port"));

    let envoy =
        repository_source("deploy/helm/joysafeter-orchestrator/templates/envoy-daemonset.yaml");
    assert!(envoy.contains("initial_metadata"));
    assert!(envoy.contains("JOYSAFETER_XDS_AUTH_TOKEN"));
    assert!(envoy.contains("x-joysafeter-node-id"));
}

#[test]
fn deployment_keeps_runner_and_ads_network_paths_separate() {
    let helm_services =
        repository_source("deploy/helm/joysafeter-orchestrator/templates/service.yaml");
    let helm_runner = manifest_document(&helm_services, "Service", "joysafeter-orchestrator");
    assert!(helm_runner.contains("targetPort: grpc"));
    let standalone_service = helm_services
        .split("{{- if eq .Values.haMode \"multi\" }}")
        .next()
        .expect("standalone Service template");
    assert!(standalone_service.contains("{{- if ne .Values.haMode \"multi\" }}"));
    assert!(standalone_service.contains("targetPort: xds"));
    let helm_ads = manifest_document(&helm_services, "Service", "joysafeter-orchestrator-xds");
    assert!(helm_ads.contains("targetPort: xds"));

    let helm_policies =
        repository_source("deploy/helm/joysafeter-orchestrator/templates/networkpolicy.yaml");
    let sandbox_egress = manifest_document(
        &helm_policies,
        "CiliumNetworkPolicy",
        "joysafeter-sandbox-egress",
    );
    assert!(sandbox_egress.contains(".Values.orchestrator.grpc.port"));
    assert!(!sandbox_egress.contains(".Values.orchestrator.xds.port"));
    let envoy_egress = manifest_document(
        &helm_policies,
        "CiliumNetworkPolicy",
        "joysafeter-envoy-egress",
    );
    assert!(envoy_egress.contains(".Values.orchestrator.xds.port"));

    let raw = repository_source("deploy/k8s/orchestrator-multi.yaml");
    let raw_runner = manifest_document(&raw, "Service", "joysafeter-orchestrator");
    assert!(raw_runner.contains("port: 9090"));
    assert!(raw_runner.contains("targetPort: grpc"));
    let raw_ads = manifest_document(&raw, "Service", "joysafeter-orchestrator-xds");
    assert!(raw_ads.contains("port: 19000"));
    assert!(raw_ads.contains("targetPort: xds"));
}
