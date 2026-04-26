"""Tests for AgentPublishService."""

import pytest

from app.services.agent_publish_service import AgentPublishService


class TestInferRuntimeKind:
    def test_graph(self):
        assert AgentPublishService._infer_runtime_kind("graph") == "graph"

    def test_hybrid(self):
        assert AgentPublishService._infer_runtime_kind("hybrid") == "graph"

    def test_code(self):
        assert AgentPublishService._infer_runtime_kind("code") == "sandbox"

    def test_unknown_defaults_to_graph(self):
        assert AgentPublishService._infer_runtime_kind("whatever") == "graph"
