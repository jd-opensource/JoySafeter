/// Kernel primitives — scheduler, sandbox management, task execution.
pub mod command_listener;
// The broker is consumed by the CredentialResolutionService in SP-3 Task 3;
// remove this allow when that wiring lands.
#[allow(dead_code)]
pub mod credential_broker;
pub mod engine_adapter;
pub mod harness_input_builder;
pub mod llm_providers;
pub mod memory_sync;
pub mod queue;
pub mod redis_coordinator;
pub mod run_spec;
pub mod sandbox_bridge;
pub mod sandbox_controller;
pub mod sandbox_lifecycle;
pub mod sandbox_resolver;
pub mod scheduler;
pub mod session_broadcaster;
pub mod task_controller;
pub mod task_runner;
