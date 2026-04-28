# backend/tests/test_core/test_observation/test_cli_extractor.py
from __future__ import annotations

import uuid

import pytest

from app.core.agent.cli_backends.base import CLIMessage
from app.core.observation.instrumentation.cli_extractor import CLIObservationExtractor
from app.core.observation.collector import ObservationCollector
from tests.test_core.test_observation.test_collector import FakeBroadcaster, FakeWriter


@pytest.fixture
def extractor():
    async def _build():
        writer = FakeWriter()
        broadcaster = FakeBroadcaster()
        collector = ObservationCollector(
            trace_id=uuid.uuid4(), execution_id=uuid.uuid4(),
            workspace_id=uuid.uuid4(), writer=writer, broadcaster=broadcaster,
        )
        root = await collector.start_agent("cli:claude_code")
        ext = CLIObservationExtractor(collector, root)
        return ext, writer, broadcaster

    return _build()


@pytest.mark.asyncio
async def test_text_accumulation_flushed_on_tool_use(extractor) -> None:
    ext, writer, _ = await extractor
    await ext.process_message(CLIMessage(type="text", content="Hello "))
    await ext.process_message(CLIMessage(type="text", content="world"))
    gens = [o for o in writer.inserted if o.type == "GENERATION"]
    assert len(gens) == 0

    await ext.process_message(CLIMessage(type="tool_use", content="web_search", tool_name="web_search", tool_input={"q": "test"}))
    gens = [o for o in writer.inserted if o.type == "GENERATION"]
    assert len(gens) == 1
    assert gens[0].output == {"completion": "Hello world"}


@pytest.mark.asyncio
async def test_tool_use_result_pair(extractor) -> None:
    ext, writer, _ = await extractor
    await ext.process_message(CLIMessage(type="tool_use", content="read_file", tool_name="read_file", tool_input={"path": "/tmp/x"}))
    tools_open = [o for o in writer.inserted if o.type == "TOOL"]
    assert len(tools_open) == 1

    await ext.process_message(CLIMessage(type="tool_result", content="file contents"))
    assert len(writer.updated) >= 1


@pytest.mark.asyncio
async def test_flush_pending_emits_final_generation(extractor) -> None:
    ext, writer, _ = await extractor
    await ext.process_message(CLIMessage(type="text", content="final output"))
    await ext.flush_pending()

    gens = [o for o in writer.inserted if o.type == "GENERATION"]
    assert len(gens) == 1
