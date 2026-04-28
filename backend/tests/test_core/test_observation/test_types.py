from __future__ import annotations

from app.core.observation.types import ObservationLevel, ObservationType


LANGFUSE_OBSERVATION_TYPES = {
    "SPAN", "EVENT", "GENERATION", "AGENT", "TOOL",
    "CHAIN", "RETRIEVER", "EMBEDDING", "EVALUATOR", "GUARDRAIL",
}

LANGFUSE_OBSERVATION_LEVELS = {"DEBUG", "DEFAULT", "WARNING", "ERROR"}


def test_observation_type_values_match_langfuse() -> None:
    actual = {t.value for t in ObservationType}
    assert actual == LANGFUSE_OBSERVATION_TYPES


def test_observation_level_values_match_langfuse() -> None:
    actual = {lv.value for lv in ObservationLevel}
    assert actual == LANGFUSE_OBSERVATION_LEVELS


def test_observation_type_is_str_enum() -> None:
    assert ObservationType.GENERATION == "GENERATION"
    assert isinstance(ObservationType.GENERATION, str)


def test_event_type_has_no_end_time_semantics() -> None:
    assert ObservationType.EVENT == "EVENT"


def test_generation_like_types() -> None:
    generation_like = {
        ObservationType.GENERATION, ObservationType.AGENT,
        ObservationType.TOOL, ObservationType.CHAIN,
        ObservationType.RETRIEVER, ObservationType.EVALUATOR,
        ObservationType.EMBEDDING, ObservationType.GUARDRAIL,
    }
    assert ObservationType.SPAN not in generation_like
    assert ObservationType.EVENT not in generation_like
