"""Pure engine readiness ranking for the quickstart understand phase."""

from __future__ import annotations

import re
from dataclasses import dataclass

_GENERAL_PRIORITY = ["native", "claude", "codex", "pi"]
_CODING_PRIORITY = ["claude", "codex", "native", "pi"]
_CODING_INTENT = [
    re.compile(
        r"\b(code|repo|repository|git|bug|fix|test|debug|typescript|javascript|python|rust)\b",
        re.I,
    ),
    re.compile(r"代码|仓库|修复|测试|调试|报错|提交|构建"),
]
_READINESS_RANK = {"ready": 0, "setup_required": 1, "unavailable": 2}


@dataclass(frozen=True)
class EngineInput:
    engine_id: str
    display_name: str
    enabled: bool


@dataclass(frozen=True)
class ConnectionInput:
    compatible_engine_ids: tuple[str, ...]
    is_default: bool
    archived: bool


@dataclass(frozen=True)
class EngineOption:
    engine_id: str
    display_name: str
    readiness: str
    compatible_connection_count: int
    has_default_connection: bool
    recommended: bool


def _priority_index(priority: list[str], engine_id: str) -> int:
    return priority.index(engine_id) if engine_id in priority else len(priority)


def recommend_engine_options(
    enabled_engines: list[EngineInput],
    connections: list[ConnectionInput],
    intent_text: str,
) -> list[EngineOption]:
    priority = _CODING_PRIORITY if any(p.search(intent_text) for p in _CODING_INTENT) else _GENERAL_PRIORITY
    active = [c for c in connections if not c.archived]

    options: list[EngineOption] = []
    for engine in enabled_engines:
        compatible = [c for c in active if engine.engine_id in c.compatible_engine_ids]
        readiness = "unavailable" if not engine.enabled else "ready" if compatible else "setup_required"
        options.append(
            EngineOption(
                engine_id=engine.engine_id,
                display_name=engine.display_name,
                readiness=readiness,
                compatible_connection_count=len(compatible),
                has_default_connection=any(c.is_default for c in compatible),
                recommended=False,
            )
        )

    options.sort(
        key=lambda o: (
            _READINESS_RANK[o.readiness],
            _priority_index(priority, o.engine_id),
            0 if o.has_default_connection else 1,
            # Final deterministic tie-break for catalog extensions not listed above.
            o.display_name,
        )
    )

    recommended_index = next((i for i, o in enumerate(options) if o.readiness != "unavailable"), None)
    return [
        EngineOption(
            o.engine_id,
            o.display_name,
            o.readiness,
            o.compatible_connection_count,
            o.has_default_connection,
            recommended=(i == recommended_index),
        )
        for i, o in enumerate(options)
    ]
