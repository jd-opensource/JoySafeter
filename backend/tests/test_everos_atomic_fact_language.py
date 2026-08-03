from __future__ import annotations

import pytest

from app.everos.component.llm.protocol import ChatMessage, ChatResponse
from app.everos.memory.repair.atomic_facts import repair_atomic_fact_markdown_text
from app.everos.memory.strategies.extract_atomic_facts import (
    _ensure_chinese_fact_text,
    _fact_is_chinese,
    _fact_is_valid,
    _parse_fact_rewrite_response,
)

pytestmark = pytest.mark.no_db


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[list[ChatMessage]] = []

    async def chat(self, messages: list[ChatMessage], **kwargs):
        self.calls.append(messages)
        return ChatResponse(content=self.responses.pop(0), model="fake")


def test_fact_is_chinese_requires_cjk_text():
    assert _fact_is_chinese("用户关注记忆聚合结果。") is True
    assert _fact_is_chinese("User cares about memory aggregation results.") is False


def test_fact_is_valid_rejects_json_like_wrong_schema():
    assert _fact_is_valid("用户关注记忆聚合结果。") is True
    assert _fact_is_valid('{"foresights":[{"foresight":"用户关注记忆聚合结果。"}]}') is False


def test_fact_is_valid_rejects_english_prose_with_chinese_terms():
    assert (
        _fact_is_valid(
            "For motor vehicles, running a red light results in a fine of "
            "200 yuan and 6 demerit points, according to 公安部令第162号."
        )
        is False
    )
    assert (
        _fact_is_valid(
            "On July 30, 2026, huajie_Sun consulted the AI assistant on the "
            "legal topic of hit-and-run sentencing (肇事逃逸怎么判刑)."
        )
        is False
    )


def test_fact_is_valid_allows_chinese_with_required_identifiers():
    assert _fact_is_valid("罚款可通过交管12123 app或交警大队窗口缴纳。") is True
    assert _fact_is_valid("huajie_Sun 于2026年7月30日咨询了肇事逃逸量刑问题。") is True
    assert _fact_is_valid("助手在UTC时间08:29说明了闯红灯处罚。") is True
    assert (
        _fact_is_valid(
            "huajie_Sun 于2026年7月30日和7月31日与agent ID为"
            "019fb0e8-1e51-7d51-8950-0f2f187e7ce8的AI助手进行了交互。"
        )
        is True
    )


async def test_ensure_chinese_fact_text_rewrites_english_fact():
    llm = _FakeLLM(['{"fact":"用户关注记忆聚合结果。"}'])

    fact = await _ensure_chinese_fact_text(
        "User cares about memory aggregation results.",
        llm,
        source_episode="The user checked memory aggregation.",
    )

    assert fact == "用户关注记忆聚合结果。"
    assert len(llm.calls) == 1


async def test_ensure_chinese_fact_text_discards_after_failed_rewrites():
    llm = _FakeLLM(
        [
            '{"fact":"Still English."}',
            '{"fact":"Still English again."}',
            '{"fact":"Still English finally."}',
        ]
    )

    fact = await _ensure_chinese_fact_text(
        "User cares about memory aggregation results.",
        llm,
        source_episode="The user checked memory aggregation.",
    )

    assert fact is None
    assert len(llm.calls) == 3


def test_parse_fact_rewrite_response_accepts_json_code_block():
    parsed = _parse_fact_rewrite_response('```json\n{"fact":"用户关注记忆聚合结果。"}\n```')

    assert parsed == "用户关注记忆聚合结果。"


def test_parse_fact_rewrite_response_coerces_foresight_schema():
    parsed = _parse_fact_rewrite_response(
        '{"foresights":[{"owner_id":"huajie_Sun","foresight":"用户关注记忆聚合结果。"}]}'
    )

    assert parsed == "用户关注记忆聚合结果。"


def test_repair_atomic_fact_markdown_text_updates_fact_only():
    text = """---
id: atomic_fact_log_huajie_Sun_2026-08-03
---
<!-- entry:af_20260803_00000001 -->
## af_20260803_00000001

**owner_id**: huajie_Sun
**timestamp**: 2026-08-03T02:42:29.560000+00:00
**parent_type**: episode
**parent_id**: ep_20260803_00000002

### Fact
User cares about memory aggregation results.
<!-- /entry:af_20260803_00000001 -->
"""

    repaired, changed = repair_atomic_fact_markdown_text(
        text,
        repairs={"af_20260803_00000001": "用户关注记忆聚合结果。"},
    )

    assert changed is True
    assert "### Fact\n用户关注记忆聚合结果。" in repaired
    assert "**parent_id**: ep_20260803_00000002" in repaired
