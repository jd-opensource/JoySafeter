use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR")?);
    // Navigate: backend/app/joysafeter_agent_gateway -> project root
    let project_root = manifest_dir
        .parent() // backend/app
        .and_then(|p| p.parent()) // backend
        .and_then(|p| p.parent()) // project root
        .expect("cannot resolve project root from CARGO_MANIFEST_DIR");

    let proto_dir = project_root.join("proto");
    let policy_stream_proto = proto_dir.join("policy_stream.proto");
    let gateway_management_proto = proto_dir.join("gateway_management.proto");

    // Compile policy_stream.proto (gateway needs client side) into OUT_DIR so
    // `tonic::include_proto!` picks it up from the standard build output.
    tonic_build::configure()
        .build_server(false)
        .build_client(true)
        .compile_protos(&[&policy_stream_proto], &[&proto_dir])?;

    // Compile gateway_management.proto (gateway needs server side for orchestrator to call)
    tonic_build::configure()
        .build_server(true)
        .build_client(false)
        .compile_protos(&[&gateway_management_proto], &[&proto_dir])?;

    println!("cargo::rerun-if-changed={}", policy_stream_proto.display());
    println!("cargo::rerun-if-changed={}", gateway_management_proto.display());
    println!("cargo::rerun-if-changed=build.rs");

    Ok(())
}
