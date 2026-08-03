from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from app.everos.component.llm.protocol import ChatMessage, ChatResponse

pytestmark = pytest.mark.no_db


class ReflectOutput(BaseModel):
    subject: str
    content: str


class FakeLLM:
    def __init__(self, responses: list[ChatResponse]) -> None:
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
        return self.responses.pop(0)


async def test_json_repairing_llm_returns_valid_json_without_repair_call():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    original = ChatResponse(
        content='{"explicit_info":[],"implicit_traits":[]}',
        model="model-a",
    )
    llm = FakeLLM([original])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return JSON")])

    assert response is original
    assert len(llm.calls) == 1


async def test_json_repairing_llm_repairs_invalid_json_with_same_llm_client():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content='{"explicit_info":[{"evidence":"用户自我介绍说"你好，我叫小杰""}]}',
        model="model-a",
    )
    repaired = ChatResponse(
        content='{"explicit_info":[{"evidence":"用户自我介绍说\\"你好，我叫小杰\\""}]}',
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return JSON")])

    assert json.loads(response.content) == {"explicit_info": [{"evidence": '用户自我介绍说"你好，我叫小杰"'}]}
    assert len(llm.calls) == 2
    repair_messages = llm.calls[1]["messages"]
    assert repair_messages[-1].role == "user"
    assert "Fix only the JSON syntax" in repair_messages[-1].content
    assert llm.calls[1]["temperature"] == 0


async def test_json_repairing_llm_retries_repair_with_previous_failure_reason():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content='{"explicit_info":[{"evidence":"用户自我介绍说"你好，我叫小杰""}]}',
        model="model-a",
    )
    still_broken = ChatResponse(
        content='{"explicit_info":[{"evidence":"用户自我介绍说"你好""}]}',
        model="model-a",
    )
    repaired = ChatResponse(
        content='{"explicit_info":[{"evidence":"用户自我介绍说\\"你好\\""}]}',
        model="model-a",
    )
    llm = FakeLLM([broken, still_broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return JSON")])

    assert json.loads(response.content) == {"explicit_info": [{"evidence": '用户自我介绍说"你好"'}]}
    assert len(llm.calls) == 3
    first_repair_prompt = llm.calls[1]["messages"][-1].content
    second_repair_prompt = llm.calls[2]["messages"][-1].content
    assert "Previous validation error:" in first_repair_prompt
    assert "JSON parse error:" in first_repair_prompt
    assert still_broken.content in second_repair_prompt
    assert "Previous validation error:" in second_repair_prompt


async def test_json_repairing_llm_defaults_to_five_repair_attempts():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"value":"bad"', model="model-a")
    still_broken = ChatResponse(content='{"value":"still bad"', model="model-a")
    repaired = ChatResponse(content='{"value":"fixed"}', model="model-a")
    llm = FakeLLM(
        [
            broken,
            still_broken,
            still_broken,
            still_broken,
            still_broken,
            repaired,
        ]
    )

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return JSON")])

    assert json.loads(response.content) == {"value": "fixed"}
    assert len(llm.calls) == 6
    final_repair_prompt = llm.calls[-1]["messages"][-1].content
    assert "Repair attempt: 5 of 5" in final_repair_prompt


async def test_json_repairing_llm_uses_larger_token_budget_for_repair():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"items":["unterminated"', model="model-a")
    repaired = ChatResponse(content='{"items":["unterminated"]}', model="model-a")
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return JSON")],
        max_tokens=128,
    )

    assert json.loads(response.content) == {"items": ["unterminated"]}
    assert llm.calls[1]["max_tokens"] > 128


async def test_json_repairing_llm_leaves_non_json_content_alone():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    original = ChatResponse(content="plain text answer", model="model-a")
    llm = FakeLLM([original])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Say hello")])

    assert response is original
    assert len(llm.calls) == 1


async def test_json_repairing_llm_parses_pydantic_response_format_without_provider_schema():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    original = ChatResponse(
        content='{"subject":"Merged","content":"Merged memory"}',
        model="model-a",
    )
    llm = FakeLLM([original])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return reflected episode JSON")],
        response_format=ReflectOutput,
    )

    assert isinstance(response.parsed, ReflectOutput)
    assert response.parsed.subject == "Merged"
    assert response.parsed.content == "Merged memory"
    assert response.content == original.content
    assert llm.calls[0]["response_format"] is None


async def test_json_repairing_llm_repairs_then_parses_pydantic_response_format():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content='{"subject":"Merged","content":"Merged "memory""}',
        model="model-a",
    )
    repaired = ChatResponse(
        content='{"subject":"Merged","content":"Merged memory"}',
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return reflected episode JSON")],
        response_format=ReflectOutput,
    )

    assert isinstance(response.parsed, ReflectOutput)
    assert response.parsed.content == "Merged memory"
    assert len(llm.calls) == 2
    assert llm.calls[0]["response_format"] is None


async def test_json_repairing_llm_repairs_pydantic_schema_invalid_response():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"subject":"Merged"}', model="model-a")
    repaired = ChatResponse(
        content='{"subject":"Merged","content":"Merged memory"}',
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return reflected episode JSON")],
        response_format=ReflectOutput,
    )

    assert isinstance(response.parsed, ReflectOutput)
    assert response.parsed.subject == "Merged"
    assert len(llm.calls) == 2
    assert "JSON object does not match response_format" in llm.calls[1]["messages"][-1].content


async def test_json_repairing_llm_does_not_repair_freeform_text_with_braces():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    original = ChatResponse(content="Use {name} in the template.", model="model-a")
    llm = FakeLLM([original])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Explain the template")])

    assert response is original
    assert len(llm.calls) == 1


async def test_json_repairing_llm_repairs_schema_invalid_agent_case_json():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"task_intent":"审计记忆提取流程"}', model="model-a")
    repaired = ChatResponse(
        content=(
            '{"task_intent":"审计记忆提取流程",'
            '"approach":"阅读源码并补测试",'
            '"quality_score":0.85,'
            '"key_insight":"case 压缩必须有 approach"}'
        ),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [
            ChatMessage(
                role="user",
                content=(
                    "Return JSON for agent case compression with fields "
                    "task_intent, approach, quality_score, key_insight."
                ),
            )
        ]
    )

    assert json.loads(response.content)["approach"] == "阅读源码并补测试"
    assert len(llm.calls) == 2
    repair_prompt = llm.calls[1]["messages"][-1].content
    assert "agent_case_compress" in repair_prompt
    assert "task_intent" in repair_prompt
    assert "approach" in repair_prompt


async def test_json_repairing_llm_accepts_explicit_schema_name():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"operations":"add skill"}', model="model-a")
    repaired = ChatResponse(content='{"operations":[]}', model="model-a")
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return JSON")],
        schema_name="agent_skill_extract",
    )

    assert json.loads(response.content) == {"operations": []}
    assert len(llm.calls) == 2
    repair_prompt = llm.calls[1]["messages"][-1].content
    assert "agent_skill_extract" in repair_prompt
    assert "operations" in repair_prompt


async def test_schema_bound_llm_injects_explicit_schema_name():
    from app.everos.component.llm.structured import (
        JSONRepairingLLMClient,
        bind_json_schema,
    )

    broken = ChatResponse(
        content='{"explicit_info":[],"implicit_traits":[]}',
        model="model-a",
    )
    repaired = ChatResponse(content='{"operations":[]}', model="model-a")
    llm = FakeLLM([broken, repaired])

    bound = bind_json_schema(JSONRepairingLLMClient(llm), "profile_update")
    response = await bound.chat(
        [
            ChatMessage(
                role="user",
                content="Return JSON with explicit_info and implicit_traits.",
            )
        ]
    )

    assert json.loads(response.content) == {"operations": []}
    assert len(llm.calls) == 2
    repair_prompt = llm.calls[1]["messages"][-1].content
    assert "profile_update" in repair_prompt
    assert "operations" in repair_prompt


async def test_json_repairing_llm_classifies_parse_errors_in_repair_prompt():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"value":"bad"', model="model-a")
    repaired = ChatResponse(content='{"value":"fixed"}', model="model-a")
    llm = FakeLLM([broken, repaired])

    await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return JSON")])

    repair_prompt = llm.calls[1]["messages"][-1].content
    assert "Validation category: json_incomplete" in repair_prompt


async def test_json_repairing_llm_classifies_schema_errors_in_repair_prompt():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content='{"explicit_info":[],"implicit_traits":[]}',
        model="model-a",
    )
    repaired = ChatResponse(content='{"operations":[]}', model="model-a")
    llm = FakeLLM([broken, repaired])

    await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return JSON")],
        schema_name="profile_update",
    )

    repair_prompt = llm.calls[1]["messages"][-1].content
    assert "Validation category: schema_missing_required_field" in repair_prompt
    assert "missing required field: operations" in repair_prompt


async def test_json_repairing_llm_repairs_atomic_fact_items_missing_content():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content='{"atomic_facts":{"atomic_fact":[123]}}',
        model="model-a",
    )
    repaired = ChatResponse(
        content=('{"atomic_facts":{"atomic_fact":["用户喜欢安静的工作环境"]}}'),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return atomic_facts JSON")])

    assert json.loads(response.content)["atomic_facts"]["atomic_fact"][0] == "用户喜欢安静的工作环境"
    assert len(llm.calls) == 2
    assert "atomic_fact_extract" in llm.calls[1]["messages"][-1].content


async def test_json_repairing_llm_accepts_atomic_fact_string_items_without_timestamp():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    original = ChatResponse(
        content='{"atomic_facts":{"atomic_fact":["用户关注字段来源"]}}',
        model="model-a",
    )
    llm = FakeLLM([original])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return atomic_facts JSON")])

    assert response is original
    assert len(llm.calls) == 1


async def test_json_repairing_llm_repairs_foresight_items_missing_required_fields():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content='{"foresights":[{"foresight":"用户下周可能继续测试记忆"}]}',
        model="model-a",
    )
    repaired = ChatResponse(
        content=(
            '{"foresights":[{'
            '"owner_id":"alice",'
            '"foresight":"用户下周可能继续测试记忆",'
            '"evidence":"用户持续询问记忆系统测试",'
            '"timestamp":1780000000000'
            "}]}"
        ),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return JSON with foresights")])

    item = json.loads(response.content)["foresights"][0]
    assert item["owner_id"] == "alice"
    assert item["evidence"] == "用户持续询问记忆系统测试"
    assert len(llm.calls) == 2
    assert "foresight_extract" in llm.calls[1]["messages"][-1].content


async def test_json_repairing_llm_does_not_require_foresight_item_timestamp():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    original = ChatResponse(
        content=(
            '{"foresights":[{'
            '"owner_id":"alice",'
            '"foresight":"用户可能会继续测试记忆",'
            '"evidence":"用户持续询问记忆系统测试"'
            "}]}"
        ),
        model="model-a",
    )
    llm = FakeLLM([original])

    response = await JSONRepairingLLMClient(llm).chat([ChatMessage(role="user", content="Return JSON with foresights")])

    assert response is original
    assert len(llm.calls) == 1


async def test_json_repairing_llm_repairs_agent_skill_operation_item_shape():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"operations":[{"op":"upsert"}]}', model="model-a")
    repaired = ChatResponse(
        content=(
            '{"operations":[{'
            '"operation":"upsert",'
            '"skill":{'
            '"name":"memory_schema_validation",'
            '"description":"Use when validating EverOS memory JSON schemas.",'
            '"content":"Check required fields before writing memory files.",'
            '"confidence":0.8,'
            '"maturity_score":0.7,'
            '"source_case_ids":["ac_20260721_0001"]'
            "}}]}"
        ),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return JSON")],
        schema_name="agent_skill_extract",
    )

    skill = json.loads(response.content)["operations"][0]["skill"]
    assert skill["name"] == "memory_schema_validation"
    assert len(llm.calls) == 2
    repair_prompt = llm.calls[1]["messages"][-1].content
    assert "agent_skill_extract" in repair_prompt
    assert "confidence" in repair_prompt


async def test_json_repairing_llm_repairs_empty_episode_content():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(content='{"title":"测试记忆","content":" "}', model="model-a")
    repaired = ChatResponse(
        content=(
            '{"title":"测试记忆",'
            '"summary":"用户正在验证记忆 JSON 校验。",'
            '"content":"用户正在验证记忆 JSON 校验的字段约束。"}'
        ),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return JSON with title and content")]
    )

    assert json.loads(response.content)["summary"] == "用户正在验证记忆 JSON 校验。"
    assert len(llm.calls) == 2
    assert "non-empty" in llm.calls[1]["messages"][-1].content


async def test_json_repairing_llm_repairs_episode_missing_summary():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content='{"title":"安全审计","content":"用户完成了仓库安全审计并记录多个发现。"}',
        model="model-a",
    )
    repaired = ChatResponse(
        content=(
            '{"title":"安全审计",'
            '"summary":"用户完成代码仓库安全审计并归纳主要风险。",'
            '"content":"用户完成了仓库安全审计并记录多个发现。"}'
        ),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return episode JSON")],
        schema_name="episode_extract",
    )

    assert json.loads(response.content)["summary"] == "用户完成代码仓库安全审计并归纳主要风险。"
    assert len(llm.calls) == 2
    assert "summary" in llm.calls[1]["messages"][-1].content


async def test_json_repairing_llm_rejects_episode_summary_copied_from_content():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    content = "用户完成了仓库安全审计并记录多个发现，包括路径遍历和命令注入。"
    broken = ChatResponse(
        content=(f'{{"title":"安全审计","summary":"{content[:18]}","content":"{content}"}}'),
        model="model-a",
    )
    repaired = ChatResponse(
        content=(f'{{"title":"安全审计","summary":"用户归纳了仓库审计中的关键安全风险。","content":"{content}"}}'),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [ChatMessage(role="user", content="Return episode JSON")],
        schema_name="episode_extract",
    )

    assert json.loads(response.content)["summary"] == "用户归纳了仓库审计中的关键安全风险。"
    assert len(llm.calls) == 2
    assert "independent summary" in llm.calls[1]["messages"][-1].content


async def test_json_repairing_llm_repairs_agent_case_score_out_of_range():
    from app.everos.component.llm.structured import JSONRepairingLLMClient

    broken = ChatResponse(
        content=(
            '{"task_intent":"修复记忆校验",'
            '"approach":"补充测试和校验",'
            '"quality_score":7,'
            '"key_insight":"分数必须归一化"}'
        ),
        model="model-a",
    )
    repaired = ChatResponse(
        content=(
            '{"task_intent":"修复记忆校验",'
            '"approach":"补充测试和校验",'
            '"quality_score":0.7,'
            '"key_insight":"分数必须归一化"}'
        ),
        model="model-a",
    )
    llm = FakeLLM([broken, repaired])

    response = await JSONRepairingLLMClient(llm).chat(
        [
            ChatMessage(
                role="user",
                content=(
                    "Return JSON for agent case compression with fields "
                    "task_intent, approach, quality_score, key_insight."
                ),
            )
        ]
    )

    assert json.loads(response.content)["quality_score"] == 0.7
    assert len(llm.calls) == 2
    assert "[0, 1]" in llm.calls[1]["messages"][-1].content
