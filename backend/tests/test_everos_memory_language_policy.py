from __future__ import annotations

import pytest

from app.everos.component.llm.protocol import ChatMessage, ChatResponse
from app.everos.memory.language_policy import (
    CHINESE_MEMORY_OUTPUT_INSTRUCTION,
    ensure_chinese_memory_llm,
)

pytestmark = pytest.mark.no_db


class _FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    async def chat(self, messages: list[ChatMessage], **kwargs):
        self.calls.append(messages)
        return ChatResponse(content="{}", model="fake")


async def test_chinese_memory_llm_prepends_system_instruction():
    llm = _FakeLLM()
    wrapped = ensure_chinese_memory_llm(llm)

    await wrapped.chat([ChatMessage(role="user", content="Return JSON.")])

    assert llm.calls
    messages = llm.calls[0]
    assert messages[0].role == "system"
    assert CHINESE_MEMORY_OUTPUT_INSTRUCTION in messages[0].content
    assert messages[1].content == "Return JSON."


def test_chinese_memory_llm_is_idempotent():
    llm = _FakeLLM()
    wrapped = ensure_chinese_memory_llm(llm)

    assert ensure_chinese_memory_llm(wrapped) is wrapped
