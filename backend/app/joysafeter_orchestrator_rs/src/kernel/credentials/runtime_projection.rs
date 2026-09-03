//! Runtime credential projection for sandbox environments and egress policy.
//!
//! This facade exposes capability-focused projections while keeping durable
//! reads, secret access, route construction, and recovery orchestration in
//! separate modules. It does not own sandbox lifecycle or xDS publication.

mod environment;
mod external_egress;
mod git_egress;
mod llm_egress;
mod recovery;

pub(crate) use environment::{resolve_agent_env_from, EnvironmentRow};
pub(crate) use external_egress::build_external_egress;
pub(crate) use git_egress::build_git_egress;
pub(crate) use llm_egress::extract_llm_egress;
#[cfg(test)]
pub(crate) use recovery::remove_agent_identity_routes;
pub(crate) use recovery::{
    rebuild_sandbox_credentials, rebuild_sandbox_credentials_with_identity_routes,
};
