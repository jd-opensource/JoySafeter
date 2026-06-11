"""Unified orchestrator error types — mirrors Rust OrchestratorError (error.rs)."""

from __future__ import annotations


class OrchestratorError(Exception):
    """Base error for all orchestrator operations."""


class DatabaseError(OrchestratorError):
    """Database query or connection errors."""


class GrpcError(OrchestratorError):
    """gRPC transport or protocol errors."""


class RedisError(OrchestratorError):
    """Redis connection or command errors."""


class DockerError(OrchestratorError):
    """Docker/container provider errors."""


class JsonError(OrchestratorError):
    """JSON serialization/deserialization errors."""


class ConfigError(OrchestratorError):
    """Configuration loading or validation errors."""


class SandboxError(OrchestratorError):
    """Sandbox lifecycle errors."""


class TaskError(OrchestratorError):
    """Task lifecycle errors."""


class InternalError(OrchestratorError):
    """Catch-all for unexpectedinternal errors."""


__all__ = [
    "OrchestratorError",
    "DatabaseError",
    "GrpcError",
    "RedisError",
    "DockerError",
    "JsonError",
    "ConfigError",
    "SandboxError",
    "TaskError",
    "InternalError",
]
