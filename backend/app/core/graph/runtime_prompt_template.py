from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render_runtime_template(text: str | None, context: Mapping[str, Any]) -> str | None:
    if text is None:
        return None

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        start, end = match.span()
        if (start > 0 and text[start - 1] == "{") or (
            end < len(text) and text[end] == "}"
        ):
            return match.group(0)
        if key not in context:
            return match.group(0)

        value = context[key]
        if value is None:
            return match.group(0)

        return str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace, text)
