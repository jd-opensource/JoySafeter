//! Compatibility module for callers that previously imported `kernel::task_runner`.
//!
//! Runner orchestration now lives in the private `kernel::runner` application
//! module; transport binding remains under `grpc`.
