from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.models.graph import AgentGraph

_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_PROMPT_CONFIG_KEYS = ("systemPrompt", "system_prompt", "prompt")


def _is_supported_placeholder_match(text: str, match: re.Match[str]) -> bool:
    start, end = match.span()
    return not ((start > 0 and text[start - 1] == "{") or (end < len(text) and text[end] == "}"))


def get_prompt_text_from_config(config: Mapping[str, Any]) -> str | None:
    for key in _PROMPT_CONFIG_KEYS:
        value = config.get(key)
        if value:
            return str(value)
    return None


def extract_runtime_template_variables(text: str | None) -> set[str]:
    if not text:
        return set()

    variables: set[str] = set()
    for match in _PLACEHOLDER_PATTERN.finditer(text):
        if _is_supported_placeholder_match(text, match):
            variables.add(match.group(1))
    return variables


def build_runtime_prompt_context(
    graph: AgentGraph,
    *,
    user_id: Any | None,
    thread_id: str | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {}

    built_ins = {
        "thread_id": thread_id,
        "user_id": str(user_id) if user_id is not None else None,
        "graph_id": str(graph.id) if getattr(graph, "id", None) is not None else None,
        "workspace_id": str(graph.workspace_id) if getattr(graph, "workspace_id", None) is not None else None,
        "graph_name": getattr(graph, "name", None),
    }
    context.update({key: value for key, value in built_ins.items() if value is not None})

    graph_variables = getattr(graph, "variables", None)
    if isinstance(graph_variables, dict):
        graph_context = graph_variables.get("context")
        if isinstance(graph_context, dict):
            context.update(graph_context)

    return context


def render_runtime_template(text: str | None, context: Mapping[str, Any]) -> str | None:
    if text is None:
        return None

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if not _is_supported_placeholder_match(text, match):
            return match.group(0)
        if key not in context:
            return match.group(0)

        value = context[key]
        if value is None:
            return match.group(0)

        return str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace, text)
