use std::path::PathBuf;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR")?);
    // Navigate: backend/app/joysafeter_orchestrator_rs -> project root
    let project_root = manifest_dir
        .parent() // backend/app
        .and_then(|p| p.parent()) // backend
        .and_then(|p| p.parent()) // project root
        .expect("cannot resolve project root from CARGO_MANIFEST_DIR");

    let proto_dir = project_root.join("proto");
    let proto_file = proto_dir.join("joysafeter.proto");

    tonic_build::configure()
        .build_server(true)
        .build_client(false)
        .out_dir(manifest_dir.join("src").join("grpc"))
        .compile_protos(&[&proto_file], &[&proto_dir])?;

    println!("cargo::rerun-if-changed={}", proto_file.display());
    println!("cargo::rerun-if-changed=build.rs");

    Ok(())
}
