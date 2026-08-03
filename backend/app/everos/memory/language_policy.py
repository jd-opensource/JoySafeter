"""Language policy for EverOS memory-generation LLM calls."""

from __future__ import annotations

from typing import Any

from app.everos.component.llm.protocol import ChatMessage, ChatResponse, LLMClient

CHINESE_MEMORY_OUTPUT_INSTRUCTION = (
    "EverOS memory output language policy: all generated memory content must be "
    "written in Simplified Chinese. This applies to profiles, episodes, atomic "
    "facts, foresights, agent cases, agent skills, reflection aggregates, titles, "
    "subjects, summaries, descriptions, evidence, and all JSON string values. "
    "Keep required JSON keys, schema field names, IDs, code identifiers, URLs, "
    "file paths, and exact quoted source text unchanged when needed, but write "
    "all explanatory or narrative text in Simplified Chinese."
)


class ChineseMemoryLLMClient:
    """LLM wrapper that enforces Chinese output for memory generation."""

    def __init__(self, delegate: LLMClient) -> None:
        self._delegate = delegate

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: Any | None = None,
        **extra: Any,
    ) -> ChatResponse:
        return await self._delegate.chat(
            _with_language_instruction(messages),
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            **extra,
        )


def ensure_chinese_memory_llm(client: LLMClient) -> LLMClient:
    """Wrap a client once with the EverOS memory Chinese-output policy."""
    if isinstance(client, ChineseMemoryLLMClient):
        return client
    return ChineseMemoryLLMClient(client)


def _with_language_instruction(messages: list[ChatMessage]) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=CHINESE_MEMORY_OUTPUT_INSTRUCTION),
        *messages,
    ]
