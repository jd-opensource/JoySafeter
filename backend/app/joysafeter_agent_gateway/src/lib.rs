//! JoySafeter Agent Gateway.
//!
//! This crate owns the security boundary between sandboxed agents and external
//! services. The first extraction slice hosts the authenticated Delta xDS
//! control plane and its policy rendering model as an independent process.

pub mod adapters;
pub mod application;
pub mod bootstrap;
pub mod config;
pub mod domain;
pub mod ids;
pub mod proto;
pub mod render;
pub mod replication;
pub mod xds;
