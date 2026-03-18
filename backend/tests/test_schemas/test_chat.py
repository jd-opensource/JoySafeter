"""Unit tests for ChatRequest schema — mode and edit_skill_id fields."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.chat import ChatRequest

# ---------------------------------------------------------------------------
# Baseline: existing fields still work
# ---------------------------------------------------------------------------


class TestChatRequestBaseline:
    """Ensure the existing ChatRequest contract is unbroken."""

    def test_minimal_request(self):
        """Only the required `message` field is needed."""
        req = ChatRequest(message="hello")
        assert req.message == "hello"
        assert req.thread_id is None
        assert req.graph_id is None
        assert req.metadata == {}

    def test_all_existing_fields(self):
        gid = uuid.uuid4()
        req = ChatRequest(
            message="hi",
            thread_id="t-1",
            graph_id=gid,
            metadata={"key": "value"},
        )
        assert req.thread_id == "t-1"
        assert req.graph_id == gid
        assert req.metadata == {"key": "value"}


# ---------------------------------------------------------------------------
# New field: mode
# ---------------------------------------------------------------------------


class TestChatRequestMode:
    """Tests for the `mode` field (Literal["skill_creator"] | None)."""

    def test_mode_defaults_to_none(self):
        req = ChatRequest(message="hello")
        assert req.mode is None

    def test_mode_accepts_skill_creator(self):
        req = ChatRequest(message="hello", mode="skill_creator")
        assert req.mode == "skill_creator"

    def test_mode_accepts_none_explicitly(self):
        req = ChatRequest(message="hello", mode=None)
        assert req.mode is None

    def test_mode_rejects_invalid_value(self):
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(message="hello", mode="invalid_mode")
        # Pydantic should mention the allowed literal
        assert "skill_creator" in str(exc_info.value).lower() or "literal" in str(exc_info.value).lower()

    def test_mode_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", mode="")

    def test_mode_rejects_numeric_value(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", mode=123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# New field: edit_skill_id
# ---------------------------------------------------------------------------


class TestChatRequestEditSkillId:
    """Tests for the `edit_skill_id` field (str | None)."""

    def test_edit_skill_id_defaults_to_none(self):
        req = ChatRequest(message="hello")
        assert req.edit_skill_id is None

    def test_edit_skill_id_accepts_string(self):
        req = ChatRequest(message="hello", edit_skill_id="skill-abc-123")
        assert req.edit_skill_id == "skill-abc-123"

    def test_edit_skill_id_accepts_none_explicitly(self):
        req = ChatRequest(message="hello", edit_skill_id=None)
        assert req.edit_skill_id is None


# ---------------------------------------------------------------------------
# Combined usage
# ---------------------------------------------------------------------------


class TestChatRequestCombined:
    """Tests for using both new fields together."""

    def test_skill_creator_with_edit_skill_id(self):
        req = ChatRequest(
            message="update the skill",
            mode="skill_creator",
            edit_skill_id="skill-42",
        )
        assert req.mode == "skill_creator"
        assert req.edit_skill_id == "skill-42"

    def test_skill_creator_without_edit_skill_id(self):
        """Creating a new skill — mode set but no edit_skill_id."""
        req = ChatRequest(message="create a new skill", mode="skill_creator")
        assert req.mode == "skill_creator"
        assert req.edit_skill_id is None

    def test_default_mode_with_all_other_fields(self):
        """New fields coexist peacefully with all existing fields."""
        gid = uuid.uuid4()
        req = ChatRequest(
            message="hi",
            thread_id="t-1",
            graph_id=gid,
            metadata={"foo": "bar"},
            mode="skill_creator",
            edit_skill_id="skill-99",
        )
        assert req.message == "hi"
        assert req.thread_id == "t-1"
        assert req.graph_id == gid
        assert req.metadata == {"foo": "bar"}
        assert req.mode == "skill_creator"
        assert req.edit_skill_id == "skill-99"

    def test_serialization_roundtrip(self):
        """model_dump → model_validate preserves new fields."""
        req = ChatRequest(
            message="test",
            mode="skill_creator",
            edit_skill_id="sk-1",
        )
        data = req.model_dump()
        restored = ChatRequest.model_validate(data)
        assert restored.mode == "skill_creator"
        assert restored.edit_skill_id == "sk-1"

    def test_json_roundtrip(self):
        """JSON serialization preserves new fields."""
        req = ChatRequest(
            message="test",
            mode="skill_creator",
            edit_skill_id="sk-1",
        )
        json_str = req.model_dump_json()
        restored = ChatRequest.model_validate_json(json_str)
        assert restored.mode == "skill_creator"
        assert restored.edit_skill_id == "sk-1"
