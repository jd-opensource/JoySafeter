//! Provider-neutral egress domain.
//!
//! Owns the shared egress policy vocabulary ([`policy`]), the credential-route
//! builders ([`llm`], [`credential`]), the standalone data-plane proxy plus its
//! orchestrator-side control client ([`gateway`]), and the K8s control adapter
//! ([`k8s_manager`]). Sandbox providers and the kernel depend *downward* on this
//! module rather than reaching sideways for policy types.
//!
//! Only [`policy`] and [`gateway`] are dependency-light (no DB/kernel) and are
//! re-exposed by `lib.rs` for the standalone `joysafeter-egress-gateway` binary.
pub mod credential;
pub mod gateway;
pub mod k8s_manager;
pub mod llm;
pub mod policy;
