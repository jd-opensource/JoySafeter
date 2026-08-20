"""Quickstart chat endpoint — streams provider responses via SSE.

Translates user intent into agent/environment/MCP credential group configurations using
tool calls, streaming text deltas and config updates back to the frontend.
"""

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, Optional, cast

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.compatibility import (
    validate_credential_data,
)
from app.joysafeter_domain.llm.model_inference_policy import (
    ModelInferenceMaterialFieldMissingError,
    build_model_inference_policy,
)
from app.joysafeter_domain.services.credential_binding_errors import raise_public_credential_error
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, require_joysafeter_write
from app.joysafeter_shared.common.stream_errors import async_error_payload
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import CredentialId, SkillId
from app.joysafeter_shared.llm.base_url import LLMBaseUrlError, validate_llm_base_url

router = APIRouter(tags=["joysafeter-quickstart"])
logger = logging.getLogger(__name__)


class QuickstartMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=50000)


class QuickstartAgentContext(BaseModel):
    """Validated agent context — only known fields, values truncated."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    model: Optional[str] = Field(default=None, max_length=100)
    engine_kind: Optional[str] = Field(default=None, max_length=50)
    system: Optional[str] = Field(default=None, max_length=5000)
    tools: Optional[list] = Field(default=None, max_length=10)
    mcp_servers: Optional[list[Any] | dict[str, Any]] = Field(default=None, max_length=10)
    skills: Optional[list] = Field(default=None, max_length=20)


class QuickstartAvailableSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: SkillId
    name: str = Field(..., min_length=1, max_length=200)
    display_title: Optional[str] = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=1000)
    latest_version: str = Field(..., min_length=1, max_length=100)


class QuickstartChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[QuickstartMessage] = Field(..., max_length=50)
    current_step: int = Field(default=1, ge=1, le=5)
    engine_kind: Literal["claude", "claude_code", "codex", "native", "pi"]
    model_credential_id: CredentialId
    agent_context: Optional[QuickstartAgentContext] = None
    available_skills: list[QuickstartAvailableSkill] = Field(default_factory=list, max_length=20)


def _build_system_prompt(
    step: int,
    agent_context: Optional[QuickstartAgentContext] = None,
    available_skills: Optional[list[QuickstartAvailableSkill]] = None,
) -> str:
    step_descriptions = {
        1: "Step 1: Choose Engine - The user selects a runtime engine in the UI.",
        2: "Step 2: Create Agent - Help the user define their agent's purpose, capabilities, and configuration.",
        3: "Step 3: Configure Environment - Based on the agent, recommend the right networking and resource configuration.",
        4: "Step 4: Authorize External Tools - Help the user set up an MCP credential group and member only when MCP credentials are needed.",
        5: "Step 5: Start Session - Generate a short test message for the session.",
    }
    step_description = step_descriptions.get(step, step_descriptions[1])

    agent_section = ""
    if agent_context:
        safe_data = agent_context.model_dump(exclude_none=True)
        pretty = json.dumps(safe_data, indent=2, ensure_ascii=False)
        agent_section = f"\n\n## Agent configured in Step 2:\n```json\n{pretty}\n```\nUse this context to make informed recommendations for the current step."

    skill_section = ""
    if step == 2:
        skill_catalog = [skill.model_dump(mode="json") for skill in available_skills or []]
        skill_section = (
            "\n\n## Available Skills\n"
            "Only attach Skill IDs from this catalog. If no listed Skill is genuinely useful, return an empty skills array. "
            "Never invent a Skill ID.\n"
            f"```json\n{json.dumps(skill_catalog, indent=2, ensure_ascii=False)}\n```"
        )

    return f"""You are an elite AI agent architect specializing in crafting high-performance agent configurations for the JoySafeter platform. Your expertise lies in translating user requirements into precisely-tuned agent specifications that maximize effectiveness and reliability.

IMPORTANT: Communicate in the same language as the user. If the user writes in Chinese, respond in Chinese.

Current step: {step_description}{agent_section}{skill_section}

## Step 1: Choose Engine
The user selects a runtime engine in the UI. Do not generate configuration in this step.

## Step 2: Create Agent

When a user describes what they want an agent to do, you will:

1. **Extract Core Intent**: Identify the fundamental purpose, key responsibilities, and success criteria for the agent.
2. **Design Expert Persona**: Create a compelling expert identity that embodies deep domain knowledge relevant to the task.
3. **Architect Comprehensive Instructions**: Develop a system field that establishes clear behavioral boundaries, provides specific methodologies, anticipates edge cases, and defines output format expectations.
4. **Optimize for Performance**: Include decision-making frameworks, quality control mechanisms, efficient workflow patterns, and escalation strategies.
5. **Create Name**: Design a concise, descriptive name that clearly indicates the agent's primary function.

If the description is clear and detailed, generate the config immediately using the `generate_agent_config` tool. If critical information is missing, ask ONE focused clarifying question before generating anything.

Every generated agent must include a professional Agent Blueprint that a user can review before launch. The blueprint must make the agent operationally explicit, not merely restate the system prompt. Include:
- mission
- responsibilities
- workflow
- boundaries
- tool and permission plan
- escalation conditions
- output contract
- success criteria
- an acceptance test with a realistic test message and observable checks

When generating config via `generate_agent_config`, provide:
- name: concise, descriptive (e.g., "Daily News Reporter", "Code Reviewer")
- description: what the agent does, when to use it (in user's language)
- system: comprehensive instructions written in second person ("You are...", "You will..."), structured for maximum clarity and effectiveness
- model: leave the final runtime model to the UI-selected engine; do not force a specific vendor here
- tools: default [{{"type": "agent_toolset_20260401"}}]
- skills: attach only useful entries from Available Skills as {{"type": "custom", "skill_id": "...", "version": "latest"}}
- mcp_servers: include only external MCP services the Agent itself must connect to, using URL entries when known
- metadata: language, schedule, topic etc.
- blueprint: the complete professional Agent Blueprint described above

## Step 3: Configure Environment
Analyze the agent's purpose, system prompt, and tools to proactively recommend the right environment:
- If the agent needs broad web access → recommend "unrestricted" networking
- If the agent only needs specific APIs/services → recommend "limited" with the specific allowed_hosts
- Use the `generate_environment_config` tool once you have enough info.

## Step 4: Authorize External Tools
An MCP credential group authorizes exactly the MCP server credentials a session may use.
- If the agent uses MCP servers that need external API keys → recommend creating an MCP credential group and include a first MCP credential member with mcp_server_url when known
- If the agent only uses built-in tools with no external credentials → suggest skipping this step and explain that the first launch stays isolated from external tools
- Use the `generate_mcp_credential_group_config` tool to create an MCP credential group with a descriptive name and optional member metadata

## Step 5: Start Session
Generate ONE short test message (1-2 sentences) that a user would send to verify the agent works.

Rules:
- Be concise. No lengthy explanations.
- Use tools when you have sufficient information. Prefer making a recommendation immediately only when the user's requirements are sufficient; otherwise ask ONE focused clarifying question.
- After using a tool, briefly explain what was configured."""


def _build_tools(step: int) -> list[dict]:
    if step == 2:
        return [
            {
                "name": "generate_agent_config",
                "description": "Generate agent configuration based on user requirements",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "model": {"type": "string"},
                        "system": {"type": "string"},
                        "tools": {"type": "array", "items": {"type": "object"}},
                        "skills": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["custom"]},
                                    "skill_id": {"type": "string"},
                                    "version": {"type": "string"},
                                },
                                "required": ["type", "skill_id", "version"],
                            },
                        },
                        "mcp_servers": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": ["url"]},
                                    "name": {"type": "string"},
                                    "url": {"type": "string"},
                                },
                                "required": ["type", "name", "url"],
                            },
                        },
                        "metadata": {"type": "object"},
                        "blueprint": {
                            "type": "object",
                            "properties": {
                                "mission": {"type": "string"},
                                "responsibilities": {"type": "array", "items": {"type": "string"}},
                                "workflow": {"type": "array", "items": {"type": "string"}},
                                "boundaries": {"type": "array", "items": {"type": "string"}},
                                "capability_plan": {
                                    "type": "object",
                                    "properties": {
                                        "skills": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        },
                                        "tools": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        },
                                        "mcp_servers": {
                                            "type": "array",
                                            "items": {"type": "object"},
                                        },
                                    },
                                    "required": ["skills", "tools", "mcp_servers"],
                                },
                                "tool_plan": {"type": "array", "items": {"type": "string"}},
                                "escalation_conditions": {"type": "array", "items": {"type": "string"}},
                                "output_contract": {"type": "array", "items": {"type": "string"}},
                                "success_criteria": {"type": "array", "items": {"type": "string"}},
                                "acceptance_test": {
                                    "type": "object",
                                    "properties": {
                                        "message": {"type": "string"},
                                        "checks": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": ["message", "checks"],
                                },
                            },
                            "required": [
                                "mission",
                                "responsibilities",
                                "workflow",
                                "boundaries",
                                "capability_plan",
                                "tool_plan",
                                "escalation_conditions",
                                "output_contract",
                                "success_criteria",
                                "acceptance_test",
                            ],
                        },
                    },
                    "required": ["name", "description", "system", "blueprint"],
                },
            }
        ]
    elif step == 3:
        return [
            {
                "name": "generate_environment_config",
                "description": "Generate environment configuration for the agent",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                        "networking": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["limited", "unrestricted"]},
                                "allowed_hosts": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["type"],
                        },
                    },
                    "required": ["name", "description", "networking"],
                },
            }
        ]
    elif step == 4:
        return [
            {
                "name": "generate_mcp_credential_group_config",
                "description": "Generate MCP credential group configuration for external tool authorization",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Descriptive name for the MCP credential group"},
                        "description": {"type": "string", "description": "What MCP server credentials this group authorizes"},
                        "mcp_server_url": {"type": "string", "description": "First MCP server URL to authorize when known"},
                        "credential_name": {"type": "string", "description": "Optional name for the first MCP credential member"},
                    },
                    "required": ["name"],
                },
            }
        ]
    return []


def _build_openai_chat_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object"}),
            },
        }
        for tool in tools
    ]


def _build_openai_responses_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object"}),
        }
        for tool in tools
    ]


def _generate_curl(tool_name: str, config: dict) -> str:
    pretty_config = json.dumps(config, indent=2, ensure_ascii=False)
    endpoints = {
        "generate_agent_config": "/v1/agents",
        "generate_environment_config": "/v1/environments",
        "generate_mcp_credential_group_config": "/v1/credential-groups",
    }
    endpoint = endpoints.get(tool_name, "/v1/unknown")
    return f"""curl -X POST $BASE_URL{endpoint} \\
  -H "Content-Type: application/json" \\
  -H "x-api-key: $API_KEY" \\
  -d '{pretty_config}'"""


def _try_parse_partial_json(input_str: str) -> Optional[dict]:
    try:
        return cast(Optional[dict], json.loads(input_str))
    except json.JSONDecodeError:
        pass

    trimmed = input_str.strip()
    if not trimmed or not trimmed.startswith("{"):
        return None

    in_string = False
    escape_next = False
    stack = []

    for ch in input_str:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in ("}", "]"):
            if stack:
                stack.pop()

    result = input_str
    if in_string:
        result += '"'

    trimmed_end = result.rstrip()
    if trimmed_end.endswith(","):
        result = trimmed_end[:-1]

    for closer in reversed(stack):
        result += closer

    try:
        return cast(Optional[dict], json.loads(result))
    except json.JSONDecodeError:
        return None


def _sse_event(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _upstream_error_message(status: int) -> str:
    if status == 401:
        return "Authentication failed — check your API key."
    if status == 429:
        return "Rate limited by upstream API. Please try again later."
    if status == 400:
        return "Invalid request to upstream API. Check your configuration."
    if status == 403:
        return "Access denied by upstream API."
    if status >= 500:
        return "Upstream API is temporarily unavailable."
    return f"Upstream API error ({status})."


def _upstream_error_code(status: int) -> str:
    if status == 401:
        return "UPSTREAM_AUTH_FAILED"
    if status == 429:
        return "UPSTREAM_RATE_LIMITED"
    if status == 400:
        return "UPSTREAM_INVALID_REQUEST"
    if status == 403:
        return "UPSTREAM_ACCESS_DENIED"
    if status >= 500:
        return "UPSTREAM_UNAVAILABLE"
    return "UPSTREAM_ERROR"


def _upstream_error_event(status: int) -> dict:
    return async_error_payload(
        code=_upstream_error_code(status),
        message=_upstream_error_message(status),
        source="upstream",
        retryable=status == 429 or status >= 500,
        status=status,
    )


def _upstream_connection_error_event(exc: httpx.HTTPError) -> dict:
    return async_error_payload(
        code="UPSTREAM_CONNECTION_FAILED",
        message=f"Failed to connect to upstream API ({exc.__class__.__name__}).",
        source="upstream",
        retryable=True,
    )


def _upstream_stream_error_event(message: str) -> dict:
    return async_error_payload(
        code="UPSTREAM_STREAM_ERROR",
        message=message or "Upstream API failed.",
        source="upstream",
        retryable=False,
    )


def _url_join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _quickstart_base_url_error(exc: LLMBaseUrlError, *, provider: str) -> InvalidRequestError:
    data = {"provider": provider, "key": exc.key, "base_url": exc.base_url}
    if exc.host:
        data["host"] = exc.host
    if exc.reason == "not_allowed":
        return InvalidRequestError(
            code="QUICKSTART_BASE_URL_NOT_ALLOWED",
            message=f"{exc.key} host is not allowlisted.",
            data=data,
            user_action="fix_input",
        )
    return InvalidRequestError(
        code="QUICKSTART_BASE_URL_INVALID",
        message=f"Invalid {exc.key}",
        data=data,
        user_action="fix_input",
    )


def _messages_to_transcript(messages: list[dict]) -> str:
    return "\n\n".join(f"{message['role']}: {message['content']}" for message in messages)


async def _stream_anthropic(
    *,
    base_url: str,
    api_key: str,
    bearer_token: bool,
    body: dict,
    current_step: int,
):
    tool_name = ""
    tool_json = ""
    in_tool_use = False

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            headers = {
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
                "accept": "text/event-stream",
            }
            if bearer_token:
                headers["authorization"] = f"Bearer {api_key}"
            else:
                headers["x-api-key"] = api_key
            async with client.stream(
                "POST",
                _url_join(base_url, "/v1/messages"),
                headers=headers,
                json=body,
            ) as response:
                if response.status_code != 200:
                    yield _sse_event(_upstream_error_event(response.status_code))
                    return

                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str == "[DONE]":
                            continue
                        try:
                            evt = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        evt_type = evt.get("type", "")

                        if evt_type == "content_block_start":
                            block = evt.get("content_block", {})
                            if block.get("type") == "tool_use":
                                tool_name = block.get("name", "")
                                tool_json = ""
                                in_tool_use = True

                        elif evt_type == "content_block_delta":
                            delta = evt.get("delta", {})
                            delta_type = delta.get("type", "")

                            if delta_type == "text_delta":
                                text = delta.get("text", "")
                                yield _sse_event({"type": "text_delta", "text": text})

                            elif delta_type == "input_json_delta":
                                partial = delta.get("partial_json", "")
                                tool_json += partial
                                config = _try_parse_partial_json(tool_json)
                                if config:
                                    yield _sse_event({"type": "config_update", "step": current_step, "config": config})

                        elif evt_type == "content_block_stop":
                            if in_tool_use:
                                try:
                                    config = json.loads(tool_json)
                                except json.JSONDecodeError:
                                    config = {}
                                yield _sse_event({"type": "config_update", "step": current_step, "config": config})

                                curl = _generate_curl(tool_name, config)
                                yield _sse_event(
                                    {"type": "step_complete", "step": current_step, "resource_id": None, "curl": curl}
                                )
                                in_tool_use = False

                        elif evt_type == "error":
                            error = evt.get("error", {})
                            msg = error.get("message", "Unknown error")
                            yield _sse_event(_upstream_stream_error_event(msg))

        except httpx.HTTPError as exc:
            log_boundary_failure(
                logger,
                boundary="quickstart_api",
                code="QUICKSTART_ANTHROPIC_STREAM_FAILED",
                message="Quickstart upstream stream failed",
                operation="stream_anthropic_messages",
                error=exc,
                data={"step": current_step},
            )
            yield _sse_event(_upstream_connection_error_event(exc))


async def _stream_openai_chat_completions(
    *,
    base_url: str,
    api_key: str,
    body: dict,
    current_step: int,
):
    tool_calls: dict[str, dict[str, str]] = {}
    completed_tool_key: Optional[str] = None

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                "POST",
                _url_join(base_url, "/chat/completions"),
                headers={
                    "authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                    "accept": "text/event-stream",
                },
                json=body,
            ) as response:
                if response.status_code != 200:
                    yield _sse_event(_upstream_error_event(response.status_code))
                    return

                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str == "[DONE]":
                            continue
                        try:
                            evt = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = evt.get("choices") or []
                        if not choices:
                            continue

                        choice = choices[0]
                        delta = choice.get("delta") or {}
                        content = delta.get("content")
                        if content:
                            yield _sse_event({"type": "text_delta", "text": content})

                        for call in delta.get("tool_calls") or []:
                            key = str(call.get("index", call.get("id", "0")))
                            state = tool_calls.setdefault(key, {"name": "", "json": ""})
                            fn = call.get("function") or {}
                            if fn.get("name"):
                                state["name"] = fn["name"]
                            if fn.get("arguments"):
                                state["json"] += fn["arguments"]
                                config = _try_parse_partial_json(state["json"])
                                if config:
                                    yield _sse_event({"type": "config_update", "step": current_step, "config": config})

                        finish_reason = choice.get("finish_reason")
                        if finish_reason in ("tool_calls", "stop") and tool_calls and completed_tool_key is None:
                            completed_tool_key = next(iter(tool_calls))
                            state = tool_calls[completed_tool_key]
                            try:
                                config = json.loads(state["json"])
                            except json.JSONDecodeError:
                                config = {}
                            yield _sse_event({"type": "config_update", "step": current_step, "config": config})
                            curl = _generate_curl(state["name"], config)
                            yield _sse_event(
                                {"type": "step_complete", "step": current_step, "resource_id": None, "curl": curl}
                            )

        except httpx.HTTPError as exc:
            log_boundary_failure(
                logger,
                boundary="quickstart_api",
                code="QUICKSTART_OPENAI_CHAT_STREAM_FAILED",
                message="Quickstart upstream stream failed",
                operation="stream_openai_chat_completions",
                error=exc,
                data={"step": current_step},
            )
            yield _sse_event(_upstream_connection_error_event(exc))


async def _stream_openai_responses(
    *,
    base_url: str,
    api_key: str,
    body: dict,
    current_step: int,
):
    tool_calls: dict[str, dict[str, str]] = {}
    completed_tool_key: Optional[str] = None

    def tool_key(evt: dict) -> str:
        return str(evt.get("item_id") or evt.get("output_index") or "0")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                "POST",
                _url_join(base_url, "/responses"),
                headers={
                    "authorization": f"Bearer {api_key}",
                    "content-type": "application/json",
                    "accept": "text/event-stream",
                },
                json=body,
            ) as response:
                if response.status_code != 200:
                    yield _sse_event(_upstream_error_event(response.status_code))
                    return

                buffer = ""
                async for chunk in response.aiter_text():
                    buffer += chunk
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data: "):
                            continue

                        data_str = line[6:]
                        if data_str == "[DONE]":
                            continue
                        try:
                            evt = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        evt_type = evt.get("type", "")

                        if evt_type in ("response.output_text.delta", "response.refusal.delta"):
                            delta = evt.get("delta", "")
                            if delta:
                                yield _sse_event({"type": "text_delta", "text": delta})

                        elif evt_type in ("response.output_item.added", "response.output_item.done"):
                            item = evt.get("item") or {}
                            if item.get("type") == "function_call":
                                key = str(item.get("id") or evt.get("output_index") or "0")
                                state = tool_calls.setdefault(key, {"name": "", "json": ""})
                                if item.get("name"):
                                    state["name"] = item["name"]
                                if item.get("arguments"):
                                    state["json"] = item["arguments"]
                                    config = _try_parse_partial_json(state["json"])
                                    if config:
                                        yield _sse_event(
                                            {"type": "config_update", "step": current_step, "config": config}
                                        )

                        elif evt_type == "response.function_call_arguments.delta":
                            key = tool_key(evt)
                            state = tool_calls.setdefault(key, {"name": "", "json": ""})
                            state["json"] += evt.get("delta", "")
                            config = _try_parse_partial_json(state["json"])
                            if config:
                                yield _sse_event({"type": "config_update", "step": current_step, "config": config})

                        elif evt_type == "response.function_call_arguments.done":
                            key = tool_key(evt)
                            state = tool_calls.setdefault(key, {"name": "", "json": ""})
                            if evt.get("arguments"):
                                state["json"] = evt["arguments"]
                            if completed_tool_key is None:
                                completed_tool_key = key
                                try:
                                    config = json.loads(state["json"])
                                except json.JSONDecodeError:
                                    config = {}
                                yield _sse_event({"type": "config_update", "step": current_step, "config": config})
                                curl = _generate_curl(state["name"], config)
                                yield _sse_event(
                                    {"type": "step_complete", "step": current_step, "resource_id": None, "curl": curl}
                                )

                        elif evt_type == "response.completed" and completed_tool_key is None:
                            response_obj = evt.get("response") or {}
                            for item in response_obj.get("output") or []:
                                if item.get("type") != "function_call":
                                    continue
                                key = str(item.get("id") or item.get("call_id") or "0")
                                state = tool_calls.setdefault(key, {"name": "", "json": ""})
                                if item.get("name"):
                                    state["name"] = item["name"]
                                if item.get("arguments"):
                                    state["json"] = item["arguments"]
                                completed_tool_key = key
                                try:
                                    config = json.loads(state["json"])
                                except json.JSONDecodeError:
                                    config = {}
                                yield _sse_event({"type": "config_update", "step": current_step, "config": config})
                                curl = _generate_curl(state["name"], config)
                                yield _sse_event(
                                    {"type": "step_complete", "step": current_step, "resource_id": None, "curl": curl}
                                )
                                break

                        elif evt_type == "response.failed":
                            response_obj = evt.get("response") or {}
                            error = response_obj.get("error") or evt.get("error") or {}
                            yield _sse_event(_upstream_stream_error_event(error.get("message", "Upstream API failed.")))

        except httpx.HTTPError as exc:
            log_boundary_failure(
                logger,
                boundary="quickstart_api",
                code="QUICKSTART_OPENAI_RESPONSES_STREAM_FAILED",
                message="Quickstart upstream stream failed",
                operation="stream_openai_responses",
                error=exc,
                data={"step": current_step},
            )
            yield _sse_event(_upstream_connection_error_event(exc))


@router.post("/chat")
async def quickstart_chat(
    req: QuickstartChatRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    application = compose_credential_application(
        db,
        auto_commit=False,
        compatibility_mode=False,
    )
    try:
        binding = build_model_inference_policy(
            get_llm_catalog(),
            project_id=auth_ctx.project_id,
            credential_id=req.model_credential_id,
            engine_kind=req.engine_kind,
            model_id=req.agent_context.model if req.agent_context is not None else None,
        )
        validated, resolution = await application.binding_service.validate_model_inference(binding)
        material = await application.material_adapter.load(validated)
    except ModelInferenceMaterialFieldMissingError as exc:
        validate_credential_data(
            exc.provider_id,
            exc.protocol_id,
            {},
        )
        raise AssertionError("Catalog profile with missing required material must fail validation") from exc
    except Exception as exc:
        raise_public_credential_error(
            exc,
            credential_id=req.model_credential_id,
            data={"engine_kind": req.engine_kind},
            not_found_user_action="fix_input",
        )
    data = {str(field_name): value for field_name, value in material.fields.items()}
    provider = resolution.provider_id
    protocol = resolution.protocol_id
    validate_credential_data(provider, protocol, data)
    base_url_key = resolution.base_url_key or "BASE_URL"
    base_url = data.get(base_url_key) or resolution.default_base_url
    if not base_url:
        raise InvalidRequestError(
            code="QUICKSTART_BASE_URL_REQUIRED",
            message=f"{base_url_key} is required for this provider",
            data={"provider": provider, "protocol": protocol, "key": base_url_key},
            user_action="fix_input",
        )
    try:
        base_url = validate_llm_base_url(base_url, key=base_url_key)
    except LLMBaseUrlError as exc:
        raise _quickstart_base_url_error(exc, provider=provider) from None
    model = data.get(resolution.model_key) if resolution.model_key else None

    system_prompt = _build_system_prompt(
        req.current_step,
        req.agent_context,
        req.available_skills,
    )
    tools = _build_tools(req.current_step)

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    stream_provider: Callable[..., AsyncIterator[str]] = _stream_anthropic
    stream_kwargs = {}

    if protocol == "anthropic_messages":
        auth_token = data.get("ANTHROPIC_AUTH_TOKEN") or ""
        api_key = auth_token or data.get("ANTHROPIC_API_KEY") or ""
        claude_body = {
            "model": model or "claude-sonnet-4-20250514",
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
            "stream": True,
        }
        if tools:
            claude_body["tools"] = tools
            if req.current_step in (2, 3, 4):
                claude_body["tool_choice"] = {"type": "tool", "name": tools[0]["name"]}

        stream_kwargs = {
            "base_url": base_url,
            "api_key": api_key,
            "bearer_token": bool(auth_token),
            "body": claude_body,
        }

    elif protocol in {"openai_responses", "chat_completions"}:
        api_key = data.get("OPENAI_API_KEY") or ""
        if protocol == "chat_completions":
            openai_tools = _build_openai_chat_tools(tools)
            chat_body = {
                "model": model or "gpt-4.1-mini",
                "messages": [{"role": "system", "content": system_prompt}, *messages],
                "stream": True,
                "max_tokens": 4096,
            }
            if openai_tools:
                chat_body["tools"] = openai_tools
                if req.current_step in (2, 3, 4):
                    chat_body["tool_choice"] = {
                        "type": "function",
                        "function": {"name": openai_tools[0]["function"]["name"]},
                    }
            stream_provider = _stream_openai_chat_completions
            stream_kwargs = {"base_url": base_url, "api_key": api_key, "body": chat_body}
        else:
            responses_tools = _build_openai_responses_tools(tools)
            responses_body = {
                "model": model or "gpt-5.3-codex",
                "instructions": system_prompt,
                "input": _messages_to_transcript(messages),
                "stream": True,
                "max_output_tokens": 4096,
            }
            if responses_tools:
                responses_body["tools"] = responses_tools
                if req.current_step in (2, 3, 4):
                    responses_body["tool_choice"] = {
                        "type": "function",
                        "name": responses_tools[0]["name"],
                    }
            stream_provider = _stream_openai_responses
            stream_kwargs = {"base_url": base_url, "api_key": api_key, "body": responses_body}
    else:
        raise InvalidRequestError(
            code="QUICKSTART_PROTOCOL_UNSUPPORTED",
            message=f"Quickstart does not support protocol '{protocol}'",
            data={"provider": provider, "protocol": protocol},
            user_action="fix_input",
        )

    async def event_generator():
        async for event in stream_provider(current_step=req.current_step, **stream_kwargs):
            yield event

        yield _sse_event({"type": "done"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
