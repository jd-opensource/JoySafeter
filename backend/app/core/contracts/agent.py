"""Canonical Agent engine/runtime kind contract values."""

from __future__ import annotations

from typing import Literal, Union, get_args

from app.common.app_errors import InvalidRequestError

EngineKind = Literal[
    "langgraph_visual",
    "langgraph_code",
    "claude_code",
    "codex",
    "openclaw",
]
ENGINE_KINDS: set[str] = set(get_args(EngineKind))

InternalEngineKind = Literal["build_copilot"]
INTERNAL_ENGINE_KINDS: set[str] = set(get_args(InternalEngineKind))

AllEngineKind = Union[EngineKind, InternalEngineKind]
ALL_ENGINE_KINDS: set[str] = ENGINE_KINDS | INTERNAL_ENGINE_KINDS

RuntimeKind = Literal["sandbox", "server"]
RUNTIME_KINDS: set[str] = set(get_args(RuntimeKind))

ENGINE_RUNTIME_MAP: dict[str, str] = {
    "langgraph_visual": "server",
    "langgraph_code": "server",
    "claude_code": "sandbox",
    "codex": "sandbox",
    "openclaw": "sandbox",
}

CLI_ENGINE_KINDS: set[str] = {k for k, v in ENGINE_RUNTIME_MAP.items() if v == "sandbox"}


def infer_runtime_kind(engine_kind: str) -> str:
    runtime_kind = ENGINE_RUNTIME_MAP.get(engine_kind)
    if not runtime_kind:
        raise InvalidRequestError(
            f"Unsupported engine_kind={engine_kind}",
            code="AGENT_ENGINE_KIND_UNSUPPORTED",
            data={"engine_kind": engine_kind},
        )
    return runtime_kind


def is_cli_engine_kind(engine_kind: str) -> bool:
    return engine_kind in CLI_ENGINE_KINDS


def normalize_engine_kind(engine_kind: str | None) -> str | None:
    return engine_kind if engine_kind in ENGINE_KINDS else None


def normalize_runtime_kind(runtime_kind: str | None) -> str | None:
    return runtime_kind if runtime_kind in RUNTIME_KINDS else None
