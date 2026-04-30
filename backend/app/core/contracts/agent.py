"""Canonical Agent definition/runtime kind contract values."""

from __future__ import annotations

from typing import Literal

from app.common.app_errors import InvalidRequestError

DefinitionKindLiteral = Literal["graph", "code", "claude_code", "codex", "openclaw"]
RuntimeKindLiteral = Literal["graph", "code", "sandbox"]

DEFINITION_KINDS: set[str] = {"graph", "code", "claude_code", "codex", "openclaw"}
CLI_DEFINITION_KINDS: set[str] = {"claude_code", "codex", "openclaw"}
RUNTIME_KINDS: set[str] = {"graph", "code", "sandbox"}
DEFINITION_RUNTIME_KIND: dict[str, str] = {
    "graph": "graph",
    "code": "code",
    "claude_code": "sandbox",
    "codex": "sandbox",
    "openclaw": "sandbox",
}


def infer_runtime_kind(definition_kind: str) -> str:
    runtime_kind = DEFINITION_RUNTIME_KIND.get(definition_kind)
    if not runtime_kind:
        raise InvalidRequestError(
            f"Unsupported definition_kind={definition_kind}",
            code="AGENT_DEFINITION_KIND_UNSUPPORTED",
            data={"definition_kind": definition_kind},
        )
    return runtime_kind


def is_cli_definition_kind(definition_kind: str) -> bool:
    return definition_kind in CLI_DEFINITION_KINDS


def normalize_definition_kind(definition_kind: str | None) -> str | None:
    return definition_kind if definition_kind in DEFINITION_KINDS else None


def normalize_runtime_kind(runtime_kind: str | None) -> str | None:
    return runtime_kind if runtime_kind in RUNTIME_KINDS else None
