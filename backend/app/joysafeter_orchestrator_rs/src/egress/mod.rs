//! Provider-neutral egress domain.
//!
//! Owns the shared egress policy vocabulary ([`policy`]), the credential-route
//! builders ([`llm`], [`credential`]), and the shared data-plane policy
//! authority. Sandbox providers and the kernel depend *downward* on this module
//! rather than reaching sideways for policy types.
pub mod authority;
pub mod credential;
pub mod enforcer;
pub mod llm;
pub mod policy;
pub mod token;
