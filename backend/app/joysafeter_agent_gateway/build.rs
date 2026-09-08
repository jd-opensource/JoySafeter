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
    let gateway_management_proto = proto_dir.join("gateway_management.proto");

    // Gateway serves the management and replication APIs and also acts as the
    // replication client while in follower mode.
    tonic_build::configure()
        .build_server(true)
        .build_client(true)
        .compile_protos(&[&gateway_management_proto], &[&proto_dir])?;

    println!(
        "cargo::rerun-if-changed={}",
        gateway_management_proto.display()
    );
    println!("cargo::rerun-if-changed=build.rs");

    Ok(())
}
