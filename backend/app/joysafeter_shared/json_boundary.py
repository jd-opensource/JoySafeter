"""Strict conversion for intentionally schema-less JSON boundaries."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import TypeAlias

from app.joysafeter_shared.ids import EntityId

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class JsonBoundaryTypeError(TypeError):
    """Raised when an unsupported value reaches a schema-less JSON boundary."""


def normalize_json_value(value: object, *, path: str = "$") -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise JsonBoundaryTypeError(f"Non-finite float at {path}")
        return value
    if isinstance(value, EntityId):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return normalize_json_value(value.value, path=path)
    if isinstance(value, Mapping):
        normalized: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise JsonBoundaryTypeError(f"Non-string mapping key at {path}: {type(key).__name__}")
            normalized[key] = normalize_json_value(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, (list, tuple)):
        return [normalize_json_value(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    raise JsonBoundaryTypeError(f"Unsupported JSON value at {path}: {type(value).__name__}")
