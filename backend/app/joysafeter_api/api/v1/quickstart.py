"""Quickstart chat endpoint — streams provider responses via SSE.

Translates user intent into agent/environment/vault configurations using
tool calls, streaming text deltas and config updates back to the frontend.
"""

import json
from typing import Literal, Optional, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.services import SecretService
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, require_joysafeter_write
from app.joysafeter_shared.database import get_db

router = APIRouter(tags=["joysafeter-quickstart"])


class QuickstartMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=50000)


class QuickstartAgentContext(BaseModel):
    """Validated agent context — only known fields, values truncated."""

    name: str = Field(default="", max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    model: Optional[str] = Field(default=None, max_length=100)
    engine_kind: Optional[str] = Field(default=None, max_length=50)
    system_prompt: Optional[str] = Field(default=None, max_length=5000)
    tools: Optional[list] = Field(default=None, max_length=10)
    mcp_servers: Optional[list] = Field(default=None, max_length=10)
    skills: Optional[list] = Field(default=None, max_length=20)
    secret_ref: Optional[str] = Field(default=None, max_length=100)

    class Config:
        extra = "ignore"


class QuickstartChatRequest(BaseModel):
    messages: list[QuickstartMessage] = Field(..., max_length=50)
    current_step: int = Field(default=1, ge=1, le=5)
    provider: Literal["claude", "claudecode", "codex", "native"] = "claude"
    secret_ref: str = ""
    agent_context: Optional[QuickstartAgentContext] = None


def _build_system_prompt(step: int, agent_context: Optional[QuickstartAgentContext] = None) -> str:
    step_descriptions = {
        1: "Step 1: Choose Engine - The user selects claudecode or codex in the UI.",
        2: "Step 2: Create Agent - Help the user define their agent's purpose, capabilities, and configuration.",
        3: "Step 3: Configure Environment - Based on the agent, recommend the right networking and resource configuration.",
        4: "Step 4: Configure Vault - Help the user set up a credential vault for MCP server secrets.",
        5: "Step 5: Start Session - Generate a short test message for the session.",
    }
    step_description = step_descriptions.get(step, step_descriptions[1])

    agent_section = ""
    if agent_context:
        safe_data = agent_context.model_dump(exclude_none=True)
        pretty = json.dumps(safe_data, indent=2, ensure_ascii=False)
        agent_section = f"\n\n## Agent configured in Step 2:\n```json\n{pretty}\n```\nUse this context to make informed recommendations for the current step."

    return f"""You are an elite AI agent architect specializing in crafting high-performance agent configurations for the JoySafeter platform. Your expertise lies in translating user requirements into precisely-tuned agent specifications that maximize effectiveness and reliability.

IMPORTANT: Communicate in the same language as the user. If the user writes in Chinese, respond in Chinese.

Current step: {step_description}{agent_section}

## Step 1: Choose Engine
The user selects either claudecode or codex in the UI. Do not generate configuration in this step.

## Step 2: Create Agent

When a user describes what they want an agent to do, you will:

1. **Extract Core Intent**: Identify the fundamental purpose, key responsibilities, and success criteria for the agent.
2. **Design Expert Persona**: Create a compelling expert identity that embodies deep domain knowledge relevant to the task.
3. **Architect Comprehensive Instructions**: Develop a system_prompt that establishes clear behavioral boundaries, provides specific methodologies, anticipates edge cases, and defines output format expectations.
4. **Optimize for Performance**: Include decision-making frameworks, quality control mechanisms, efficient workflow patterns, and escalation strategies.
5. **Create Name**: Design a concise, descriptive name that clearly indicates the agent's primary function.

If the description is clear and detailed, generate the config immediately using the `generate_agent_config` tool. If unclear, ask ONE focused clarifying question.

When generating config via `generate_agent_config`, provide:
- name: concise, descriptive (e.g., "Daily News Reporter", "Code Reviewer")
- description: what the agent does, when to use it (in user's language)
- system_prompt: comprehensive instructions written in second person ("You are...", "You will..."), structured for maximum clarity and effectiveness
- model: leave the final runtime model to the UI-selected engine; do not force a specific vendor here
- tools: default [{{"type": "agent_toolset_20260401"}}]
- metadata: language, schedule, topic etc.

## Step 3: Configure Environment
Analyze the agent's purpose, system prompt, and tools to proactively recommend the right environment:
- If the agent needs broad web access → recommend "unrestricted" networking
- If the agent only needs specific APIs/services → recommend "limited" with the specific allowed_hosts
- Use the `generate_environment_config` tool once you have enough info.

## Step 4: Configure Vault
A vault stores credentials (API keys, OAuth tokens) that MCP servers need at runtime.
- If the agent uses MCP tools that need external API keys → recommend creating a vault
- If the agent only uses built-in tools with no external credentials → suggest skipping this step
- Use the `generate_vault_config` tool to create a vault with a descriptive name

## Step 5: Start Session
Generate ONE short test message (1-2 sentences) that a user would send to verify the agent works.

Rules:
- Be concise. No lengthy explanations.
- Use tools when you have sufficient information. Prefer making a recommendation immediately over asking questions.
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
                        "system_prompt": {"type": "string"},
                        "tools": {"type": "array", "items": {"type": "object"}},
                        "metadata": {"type": "object"},
                    },
                    "required": ["name", "description", "system_prompt"],
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
                "name": "generate_vault_config",
                "description": "Generate credential vault configuration for MCP server secrets",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Descriptive name for the vault"},
                        "description": {"type": "string", "description": "What credentials this vault stores"},
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
        "generate_vault_config": "/v1/vaults",
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


def _url_join(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _messages_to_transcript(messages: list[dict]) -> str:
    return "\n\n".join(f"{message['role']}: {message['content']}" for message in messages)


async def _stream_anthropic(
    *,
    base_url: str,
    api_key: str,
    body: dict,
    current_step: int,
):
    tool_name = ""
    tool_json = ""
    in_tool_use = False

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            async with client.stream(
                "POST",
                _url_join(base_url, "/v1/messages"),
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                    "accept": "text/event-stream",
                },
                json=body,
            ) as response:
                if response.status_code != 200:
                    yield _sse_event({"type": "error", "message": _upstream_error_message(response.status_code)})
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
                            yield _sse_event({"type": "error", "message": msg})

        except httpx.HTTPError:
            yield _sse_event({"type": "error", "message": "Failed to connect to upstream API."})


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
                    yield _sse_event({"type": "error", "message": _upstream_error_message(response.status_code)})
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

        except httpx.HTTPError:
            yield _sse_event({"type": "error", "message": "Failed to connect to upstream API."})


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
                    yield _sse_event({"type": "error", "message": _upstream_error_message(response.status_code)})
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
                            yield _sse_event({"type": "error", "message": error.get("message", "Upstream API failed.")})

        except httpx.HTTPError:
            yield _sse_event({"type": "error", "message": "Failed to connect to upstream API."})


@router.post("/chat")
async def quickstart_chat(
    req: QuickstartChatRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    svc = SecretService(db)
    secret = await svc.get_secret_by_name(req.secret_ref, project_id=auth_ctx.project_id)
    if not secret:
        raise HTTPException(404, "Secret not found or missing required keys")

    data = svc.get_secret_data(secret)
    provider = "codex" if req.provider == "codex" else "claude"

    # SSRF protection: block cloud metadata endpoints, allow internal network
    from app.joysafeter_shared.security.ssrf_guard import SSRFError, validate_url

    system_prompt = _build_system_prompt(req.current_step, req.agent_context)
    tools = _build_tools(req.current_step)

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    stream_provider = _stream_anthropic
    stream_kwargs = {}

    if provider == "claude":
        api_key = data.get("ANTHROPIC_AUTH_TOKEN") or data.get("ANTHROPIC_API_KEY") or ""
        base_url = data.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
        try:
            validate_url(base_url, allow_http=True, allow_private=True, context="ANTHROPIC_BASE_URL")
        except SSRFError:
            raise HTTPException(400, "Invalid ANTHROPIC_BASE_URL")

        if not api_key:
            raise HTTPException(404, "Secret not found or missing required keys")

        model = data.get("MODEL") or data.get("ANTHROPIC_MODEL") or "claude-sonnet-4-20250514"
        claude_body = {
            "model": model,
            "max_tokens": 4096,
            "system": system_prompt,
            "messages": messages,
            "stream": True,
        }
        if tools:
            claude_body["tools"] = tools
            if req.current_step in (2, 3, 4):
                claude_body["tool_choice"] = {"type": "tool", "name": tools[0]["name"]}

        stream_kwargs = {"base_url": base_url, "api_key": api_key, "body": claude_body}

    else:
        api_key = data.get("OPENAI_API_KEY") or ""
        base_url = data.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        try:
            validate_url(base_url, allow_http=True, allow_private=True, context="OPENAI_BASE_URL")
        except SSRFError:
            raise HTTPException(400, "Invalid OPENAI_BASE_URL")

        if not api_key:
            raise HTTPException(404, "Secret not found or missing required keys")

        model = data.get("OPENAI_MODEL") or "gpt-5.3-codex"
        protocol = getattr(secret, "protocol", "") or ""
        if protocol == "chat_completions":
            openai_tools = _build_openai_chat_tools(tools)
            chat_body = {
                "model": model,
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
                "model": model,
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
