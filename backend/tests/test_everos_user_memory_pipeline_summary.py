from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.everos.component.llm.protocol import ChatResponse
from app.everos.memory import Episode
from app.everos.memory.extract.pipeline import user_memory

pytestmark = pytest.mark.no_db


class FakeLLM:
    def __init__(self, responses: list[ChatResponse | Exception]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def chat(
        self,
        messages,
        *,
        model=None,
        temperature=None,
        max_tokens=None,
        response_format=None,
        **extra,
    ):
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
                "extra": extra,
            }
        )
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeEpisodeExtractor:
    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    async def aextract(self, cell, *, sender_id, prompt):
        self.calls.append({"cell": cell, "sender_id": sender_id, "prompt": prompt})
        return self.responses.pop(0)


def _episode(*, content: str, summary: str) -> Episode:
    return Episode(
        owner_id="user-1",
        episode=content,
        timestamp=1,
        parent_id="memcell-1",
        subject="安全审计",
        summary=summary,
    )


def test_episode_entry_body_requires_non_empty_limited_subject():
    episode = _episode(
        content="用户完成仓库安全审计，并记录了路径遍历和命令注入风险。后续计划修复。",
        summary="用户归纳了仓库审计中的关键风险。",
    ).model_copy(
        update={
            "subject": (
                "用户完成仓库安全审计，并记录了路径遍历和命令注入风险。"
                "这是第二句话，不应该进入主题。"
            )
        }
    )

    _inline, sections = user_memory._episode_to_entry_body(episode)

    assert sections["Subject"] == "用户完成仓库安全审计，并记录了路径遍历和命令注入风险。"


def test_episode_entry_body_falls_back_to_content_for_empty_subject():
    episode = _episode(
        content="用户完成仓库安全审计，并记录了路径遍历和命令注入风险。后续计划修复。",
        summary="用户归纳了仓库审计中的关键风险。",
    ).model_copy(update={"subject": ""})

    _inline, sections = user_memory._episode_to_entry_body(episode)

    assert sections["Subject"] == "用户完成仓库安全审计，并记录了路径遍历和命令注入风险。"


def test_episode_subject_is_limited_to_140_characters():
    episode = _episode(
        content="fallback content",
        summary="用户归纳了仓库审计中的关键风险。",
    ).model_copy(update={"subject": "A" * 180})

    _inline, sections = user_memory._episode_to_entry_body(episode)

    assert sections["Subject"] == "A" * 140


async def test_invalid_episode_summary_uses_secondary_llm_summary():
    content = "用户完成了仓库安全审计并记录多个发现，包括路径遍历和命令注入。"
    episode = _episode(content=content, summary=content[:18])
    llm = FakeLLM(
        [
            ChatResponse(
                content='{"summary":"用户总结了安全审计中的关键漏洞发现。"}',
                model="model-a",
            )
        ]
    )

    fixed = await user_memory._ensure_episode_summary(episode, llm)

    assert fixed.summary == "用户总结了安全审计中的关键漏洞发现。"
    assert len(llm.calls) == 1
    assert "independent summary" in llm.calls[0]["messages"][0].content


async def test_secondary_summary_failure_falls_back_to_content_truncation():
    content = "用户完成了仓库安全审计并记录多个发现。" * 20
    episode = _episode(content=content, summary=content[:50])
    llm = FakeLLM([RuntimeError("llm unavailable")])

    fixed = await user_memory._ensure_episode_summary(episode, llm)

    assert fixed.summary == "记忆摘要：安全审计"
    assert not content.startswith(fixed.summary)
    assert len(llm.calls) == 1


async def test_valid_episode_summary_does_not_call_secondary_llm():
    content = "用户完成了仓库安全审计并记录多个发现，包括路径遍历和命令注入。"
    episode = _episode(content=content, summary="用户归纳了仓库审计中的关键风险。")
    llm = FakeLLM([])

    fixed = await user_memory._ensure_episode_summary(episode, llm)

    assert fixed is episode
    assert llm.calls == []


async def test_valid_episode_summary_is_limited_to_three_sentences():
    content = "用户完成了仓库安全审计并记录多个发现，包括路径遍历和命令注入。"
    episode = _episode(
        content=content,
        summary=(
            "用户完成了仓库安全审计。"
            "审计记录了路径遍历风险。"
            "审计记录了命令注入风险。"
            "后续还讨论了修复优先级。"
        ),
    )
    llm = FakeLLM([])

    fixed = await user_memory._ensure_episode_summary(episode, llm)

    assert fixed.summary == (
        "用户完成了仓库安全审计。"
        "审计记录了路径遍历风险。"
        "审计记录了命令注入风险。"
    )
    assert llm.calls == []


async def test_episode_extraction_retries_invalid_summary_three_times():
    content = "用户完成了仓库安全审计并记录多个发现，包括路径遍历和命令注入。"
    extractor = FakeEpisodeExtractor(
        [
            SimpleNamespace(episode=content, summary=content[:18]),
            SimpleNamespace(episode=content, summary=content[:20]),
            SimpleNamespace(episode=content, summary="用户归纳了仓库审计中的关键风险。"),
        ]
    )

    result = await user_memory._extract_episode_with_summary_retry(
        extractor,
        cell=object(),
        prompt="episode prompt",
    )

    assert result.summary == "用户归纳了仓库审计中的关键风险。"
    assert len(extractor.calls) == 3
