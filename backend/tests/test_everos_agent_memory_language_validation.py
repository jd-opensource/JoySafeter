from __future__ import annotations

import pytest
from everalgo.types import AgentSkill as AlgoAgentSkill

from app.everos.memory.chinese_validation import is_valid_chinese_memory_text
from app.everos.memory.models import AgentCase
from app.everos.memory.strategies.extract_agent_case import (
    _agent_case_to_entry_body,
)
from app.everos.memory.strategies.extract_agent_skill import (
    _agent_skill_is_valid_chinese,
)

pytestmark = pytest.mark.no_db


def test_chinese_memory_text_rejects_english_prose_with_chinese_terms():
    assert is_valid_chinese_memory_text("助手完成了代码修改并验证测试。") is True
    assert (
        is_valid_chinese_memory_text(
            "The agent fixed the memory aggregation bug (记忆聚合)."
        )
        is False
    )
    assert (
        is_valid_chinese_memory_text(
            "agent ID为019fb0e8-1e51-7d51-8950-0f2f187e7ce8的AI助手完成了修复。"
        )
        is True
    )


def test_agent_case_to_entry_body_rejects_non_chinese_fields():
    case = AgentCase(
        owner_id="agent-1",
        session_id="session-1",
        parent_id="mc-1",
        timestamp=1,
        task_intent="The agent fixed memory aggregation (记忆聚合).",
        approach="助手读取日志并修改代码。",
        quality_score=0.8,
    )

    with pytest.raises(ValueError, match="non-Chinese"):
        _agent_case_to_entry_body(case)


def test_agent_case_to_entry_body_accepts_chinese_fields_with_agent_id():
    case = AgentCase(
        owner_id="agent-1",
        session_id="session-1",
        parent_id="mc-1",
        timestamp=1,
        task_intent="修复记忆聚合失败问题。",
        approach="agent ID为019fb0e8的AI助手读取日志、定位问题并修改代码。",
        key_insight="根因是LLM返回格式不稳定。",
        quality_score=0.8,
    )

    _inline, sections = _agent_case_to_entry_body(case)

    assert sections["TaskIntent"] == "修复记忆聚合失败问题。"


def test_agent_skill_validation_rejects_non_chinese_description():
    skill = AlgoAgentSkill(
        id="skill-1",
        cluster_id="cluster-1",
        name="memory_repair",
        description="Fix memory aggregation bugs (记忆聚合).",
        content="助手应读取日志、定位失败原因并补充测试。",
        confidence=0.8,
        maturity_score=0.7,
        source_case_ids=["case-1"],
    )

    assert _agent_skill_is_valid_chinese(skill) is False


def test_agent_skill_validation_accepts_chinese_skill_with_snake_case_name():
    skill = AlgoAgentSkill(
        id="skill-1",
        cluster_id="cluster-1",
        name="memory_repair",
        description="用于修复记忆聚合失败和历史记忆格式问题。",
        content="助手应读取日志、定位失败原因并补充测试。",
        confidence=0.8,
        maturity_score=0.7,
        source_case_ids=["case-1"],
    )

    assert _agent_skill_is_valid_chinese(skill) is True
