"""
Canonical observation types — the single source of truth for observation tracing.

Used by ObservationCollector to emit observation events to the trace tree.
"""

from __future__ import annotations

from enum import StrEnum


class ObservationType(StrEnum):
    SPAN = "SPAN"
    EVENT = "EVENT"
    GENERATION = "GENERATION"
    AGENT = "AGENT"
    TOOL = "TOOL"
    CHAIN = "CHAIN"
    RETRIEVER = "RETRIEVER"
    EMBEDDING = "EMBEDDING"
    EVALUATOR = "EVALUATOR"
    GUARDRAIL = "GUARDRAIL"


class ObservationLevel(StrEnum):
    DEBUG = "DEBUG"
    DEFAULT = "DEFAULT"
    WARNING = "WARNING"
    ERROR = "ERROR"
