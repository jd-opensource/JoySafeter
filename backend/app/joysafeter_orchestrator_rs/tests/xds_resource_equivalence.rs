//! Proves the compiled xDS resource bytes are byte-identical across the
//! tonic / envoy-types migration. Run once on the pre-migration tree to write
//! the golden fixtures; the post-migration tree must reproduce them exactly.
//!
//! The oracle serializes each compiled resource's protobuf `Any` payload
//! (`type_url` + `value`) in the snapshot's deterministic BTreeMap order. The
//! `value` bytes ARE the encoded Envoy Listener/Route/Cluster — exactly the
//! wire output the spec requires to stay unchanged (see the design's
//! "Risks and rollback" section).

use std::path::PathBuf;

use joysafeter_orchestrator::xds::compiler::{compile_kubernetes, CompileInput, CompilerConfig};
use joysafeter_orchestrator::xds::policy::POLICY_SCHEMA_VERSION;
use joysafeter_orchestrator::xds::snapshot::CompiledSnapshot;

const DIGEST: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

fn golden_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/xds_golden")
}

/// A fixed, secret-free policy input mirroring the in-module
/// `compiles_deterministic_lds_rds_cds_without_secret_values` test in
/// `src/xds/compiler.rs`.
fn policy_json() -> Vec<u8> {
    serde_json::to_vec(&serde_json::json!([{
        "sandbox_id": "018ff000-0000-7000-8000-000000000001",
        "project_id": null,
        "mode": "limited",
        "credential_routes": [{
            "route_id": "llm",
            "consumer_route_id": "llm",
            "kind": "llm",
            "match_authority": "llm.joysafeter.internal",
            "match_path": {"kind": "prefix", "value": "/"},
            "methods": ["POST"],
            "upstream": {"scheme": "https", "host": "api.example.com", "port": 443, "base_path": "/v1", "protocol": "auto"},
            "credential_ref": {"kind": "llm", "secret_name": "provider", "secret_key": "token"},
            "inject_header": "authorization",
            "inject_scheme": {"kind": "bearer"},
            "remove_headers": ["authorization", "x-api-key"],
            "timeout_profile": "streaming",
            "websocket": false
        }],
        "allowed_public_hosts": ["downloads.example.com"],
        "denied_cidrs": ["10.0.0.0/8"]
    }]))
    .unwrap()
}

/// Deterministically flatten a compiled snapshot to bytes. Ordering is provided
/// by the snapshot's nested `BTreeMap`s; each entry contributes its type URL,
/// resource name, and the length-framed `Any` payload.
fn canonical_bytes(snapshot: &CompiledSnapshot) -> Vec<u8> {
    let mut out = Vec::new();
    out.extend_from_slice(snapshot.group_key.as_bytes());
    out.push(0);
    out.extend_from_slice(&snapshot.generation.to_le_bytes());
    out.extend_from_slice(snapshot.version.as_bytes());
    out.push(0);
    for (type_url, typed) in &snapshot.resources {
        for (name, any) in typed {
            out.extend_from_slice(type_url.as_bytes());
            out.push(0);
            out.extend_from_slice(name.as_bytes());
            out.push(0);
            out.extend_from_slice(any.type_url.as_bytes());
            out.push(0);
            out.extend_from_slice(&(any.value.len() as u64).to_le_bytes());
            out.extend_from_slice(&any.value);
        }
    }
    out
}

fn encode_case(case: &str) -> Vec<u8> {
    let config = CompilerConfig::default();
    let policies = match case {
        "kubernetes-basic" => policy_json(),
        other => panic!("unknown case {other}"),
    };
    let snapshot = compile_kubernetes(
        &config,
        CompileInput {
            snapshot_group_key: "v2:node-a",
            source_group_key: "v2:node-a",
            generation: 42,
            content_sha256: DIGEST,
            policy_schema_version: POLICY_SCHEMA_VERSION,
            desired_policies: &policies,
        },
    )
    .expect("compile");
    canonical_bytes(&snapshot)
}

fn check(case: &str) {
    let got = encode_case(case);
    let path = golden_dir().join(format!("{case}.bin"));
    if std::env::var("UPDATE_XDS_GOLDEN").is_ok() || !path.exists() {
        std::fs::create_dir_all(golden_dir()).unwrap();
        std::fs::write(&path, &got).unwrap();
        return;
    }
    let want = std::fs::read(&path).expect("golden fixture");
    assert_eq!(got, want, "compiled xDS bytes for `{case}` changed");
}

#[test]
fn xds_resource_bytes_match_golden() {
    check("kubernetes-basic");
}
