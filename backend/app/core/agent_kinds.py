"""Compatibility facade for Agent definition/runtime kind values."""

from __future__ import annotations

from app.core.contracts.agent import (
    CLI_DEFINITION_KINDS,
    DEFINITION_KINDS,
    DEFINITION_RUNTIME_KIND,
    RUNTIME_KINDS,
    DefinitionKindLiteral,
    RuntimeKindLiteral,
    infer_runtime_kind,
    is_cli_definition_kind,
    normalize_definition_kind,
    normalize_runtime_kind,
)

SUPPORTED_DEFINITION_KINDS = DEFINITION_KINDS
SUPPORTED_RUNTIME_KINDS = RUNTIME_KINDS

__all__ = [
    "CLI_DEFINITION_KINDS",
    "DEFINITION_KINDS",
    "DEFINITION_RUNTIME_KIND",
    "DefinitionKindLiteral",
    "RUNTIME_KINDS",
    "RuntimeKindLiteral",
    "SUPPORTED_DEFINITION_KINDS",
    "SUPPORTED_RUNTIME_KINDS",
    "infer_runtime_kind",
    "is_cli_definition_kind",
    "normalize_definition_kind",
    "normalize_runtime_kind",
]
