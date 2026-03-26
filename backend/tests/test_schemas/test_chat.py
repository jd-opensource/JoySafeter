"""Unit tests for ChatRequest schema — generic chat-only fields."""

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
# Metadata handling
# ---------------------------------------------------------------------------


class TestChatRequestMetadata:
    """Ensure metadata remains flexible but scoped to generic chat context."""

    def test_metadata_defaults_to_empty_dict(self):
        req = ChatRequest(message="hello")
        assert req.metadata == {}

    def test_metadata_is_copied(self):
        meta = {"foo": "bar"}
        req = ChatRequest(message="hello", metadata=meta)
        assert req.metadata == {"foo": "bar"}
        meta["foo"] = "baz"
        assert req.metadata == {"foo": "bar"}

    def test_metadata_accepts_files_list(self):
        files = [
            {"filename": "notes.md", "path": "/tmp/notes.md", "size": 12},
            {"filename": "plan.txt", "path": "/tmp/plan.txt", "size": 8},
        ]
        req = ChatRequest(message="hi", metadata={"files": files})
        assert req.metadata["files"] == files


# ---------------------------------------------------------------------------
# Extra field rejection
# ---------------------------------------------------------------------------


class TestChatRequestExtraFields:
    """ChatRequest should stay generic and forbid transport-only fields."""

    def test_mode_field_is_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", mode="skill_creator")  # type: ignore[arg-type]

    def test_edit_skill_id_field_is_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(message="hello", edit_skill_id="skill-1")  # type: ignore[arg-type]
