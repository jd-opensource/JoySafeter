//! Renders egress policy into typed Envoy xDS resources (Cluster/Listener).
//!
//! This is the resource-*rendering* half of the Envoy integration; the wire
//! delivery and control-plane state live in [`crate::xds`].

use envoy_types::pb::google::protobuf::Any;
use prost::Message;

mod cluster;
mod listener;

pub const CLUSTER_TYPE_URL: &str = "type.googleapis.com/envoy.config.cluster.v3.Cluster";
pub const LISTENER_TYPE_URL: &str = "type.googleapis.com/envoy.config.listener.v3.Listener";

pub use cluster::encode_cluster_any;
pub use listener::encode_listener_any;

/// Helper: wrap a prost message in an `Any` with the given type URL.
fn pack_any<M: Message>(type_url: &str, msg: &M) -> Any {
    let mut buf = Vec::new();
    // encode into a Vec never fails for a valid message
    msg.encode(&mut buf).expect("prost encode into Vec");
    Any {
        type_url: type_url.to_string(),
        value: buf,
    }
}

#[cfg(test)]
#[path = "../../tests/unit/render/render_test.rs"]
mod tests;
