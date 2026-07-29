/// gRPC server and generated protobuf types.
pub mod server;

/// Generated protobuf types re-export.
#[allow(clippy::all)]
#[allow(non_camel_case_types)]
pub mod proto {
    include!("joysafeter.rs");
}
