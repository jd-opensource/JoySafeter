"""Unit tests for ChatRequest schema."""

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
# mode and edit_skill_id removed — verify they are no longer accepted
# ---------------------------------------------------------------------------


class TestChatRequestRemovedFields:
    """Verify that removed fields (mode, edit_skill_id) are no longer on the schema.

    These fields were removed as part of the unification to graph_id-based routing.
    They should not be accepted as top-level fields anymore.
    """

    def test_mode_field_not_present(self):
        req = ChatRequest(message="hello")
        assert not hasattr(req, "mode")

    def test_edit_skill_id_field_not_present(self):
        req = ChatRequest(message="hello")
        assert not hasattr(req, "edit_skill_id")


# ---------------------------------------------------------------------------
# metadata can carry arbitrary data (edit_skill_id, files, etc.)
# ---------------------------------------------------------------------------


class TestChatRequestMetadata:
    """Verify metadata can carry skill editing info and files."""

    def test_metadata_with_edit_skill_id(self):
        req = ChatRequest(
            message="update the skill",
            metadata={"edit_skill_id": "skill-42"},
        )
        assert req.metadata["edit_skill_id"] == "skill-42"

    def test_metadata_with_files(self):
        req = ChatRequest(
            message="analyze this",
            metadata={"files": [{"filename": "app.apk", "path": "/tmp/app.apk", "size": 1024}]},
        )
        assert len(req.metadata["files"]) == 1

    def test_metadata_with_both(self):
        req = ChatRequest(
            message="edit skill with file",
            metadata={
                "edit_skill_id": "skill-99",
                "files": [{"filename": "f.txt", "path": "/tmp/f.txt", "size": 10}],
            },
        )
        assert req.metadata["edit_skill_id"] == "skill-99"
        assert len(req.metadata["files"]) == 1

    def test_serialization_roundtrip(self):
        """model_dump -> model_validate preserves metadata."""
        req = ChatRequest(
            message="test",
            metadata={"edit_skill_id": "sk-1", "custom": "value"},
        )
        data = req.model_dump()
        restored = ChatRequest.model_validate(data)
        assert restored.metadata["edit_skill_id"] == "sk-1"
        assert restored.metadata["custom"] == "value"

    def test_json_roundtrip(self):
        """JSON serialization preserves metadata."""
        gid = uuid.uuid4()
        req = ChatRequest(
            message="test",
            graph_id=gid,
            metadata={"edit_skill_id": "sk-1"},
        )
        json_str = req.model_dump_json()
        restored = ChatRequest.model_validate_json(json_str)
        assert restored.graph_id == gid
        assert restored.metadata["edit_skill_id"] == "sk-1"
