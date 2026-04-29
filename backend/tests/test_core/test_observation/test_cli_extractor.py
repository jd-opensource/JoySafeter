# backend/tests/test_core/test_observation/test_cli_extractor.py
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.agent.cli_backends.base import CLIMessage
from app.core.observation.instrumentation.cli_extractor import CLIObservationExtractor
from app.core.observation.collector import ObservationCollector
from app.core.observation.otel.span_wrapper import ObservationSpan


class _CapturingSession:
    """Fake async session that captures Observation rows added via add_all."""

    def __init__(self) -> None:
        self.rows: list = []

    def add_all(self, objs: list) -> None:
        self.rows.extend(objs)

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.fixture
async def extractor_env():
    session = _CapturingSession()

    async def session_factory():
        return session

    collector = ObservationCollector(
        trace_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        db_session_factory=session_factory,
        broadcast_fn=None,
    )
    root = collector.start_agent("cli:claude_code")
    ext = CLIObservationExtractor(collector, root)
    return ext, collector, session


@pytest.mark.asyncio
async def test_text_accumulation_flushed_on_tool_use(extractor_env) -> None:
    ext, collector, session = extractor_env
    await ext.process_message(CLIMessage(type="text", content="Hello "))
    await ext.process_message(CLIMessage(type="text", content="world"))

    # Drain persistence processor to capture what has been written so far
    await asyncio.sleep(0.5)
    gens_before = [r for r in session.rows if r.type == "GENERATION"]
    assert len(gens_before) == 0

    # A tool_use triggers flush of accumulated text -> generation span
    await ext.process_message(
        CLIMessage(
            type="tool_use",
            content="web_search",
            tool_name="web_search",
            tool_input={"q": "test"},
        )
    )
    # Wait for the persistence processor drain loop
    await asyncio.sleep(0.5)
    gens = [r for r in session.rows if r.type == "GENERATION"]
    assert len(gens) == 1
    assert gens[0].output == {"completion": "Hello world"}

    await collector.finalize()


@pytest.mark.asyncio
async def test_tool_use_result_pair(extractor_env) -> None:
    ext, collector, session = extractor_env
    await ext.process_message(
        CLIMessage(
            type="tool_use",
            content="read_file",
            tool_name="read_file",
            tool_input={"path": "/tmp/x"},
        )
    )
    await asyncio.sleep(0.5)
    # Tool span is not yet ended (no result yet), so it won't appear in rows yet

    await ext.process_message(CLIMessage(type="tool_result", content="file contents"))
    await asyncio.sleep(0.5)
    tools = [r for r in session.rows if r.type == "TOOL"]
    assert len(tools) >= 1
    # The tool should have the result output set
    assert tools[0].output == {"result": "file contents"}

    await collector.finalize()


@pytest.mark.asyncio
async def test_flush_pending_emits_final_generation(extractor_env) -> None:
    ext, collector, session = extractor_env
    await ext.process_message(CLIMessage(type="text", content="final output"))
    await ext.flush_pending()

    await asyncio.sleep(0.5)
    gens = [r for r in session.rows if r.type == "GENERATION"]
    assert len(gens) == 1

    await collector.finalize()
