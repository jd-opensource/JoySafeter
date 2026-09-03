//! Backend-neutral egress policy model and validation.

mod credentials;
mod model;
mod validation;

pub use credentials::{SandboxCredentials, UpstreamTarget};
pub use model::*;
pub use validation::validate_egress_policy;

pub(crate) use credentials::{
    escape_envoy_header_value, group_route_specs_by_host, proxy_authorization_value,
    upstream_authority, upstream_headers_to_remove,
};

#[cfg(test)]
#[path = "../../tests/unit/domain/egress_policy_test.rs"]
mod tests;
