"""Quickstart chat endpoint — streams Claude responses via SSE.

Translates user intent into agent/environment/vault configurations using
Claude tool_use, streaming text deltas and config updates back to the frontend.
"""

import json
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, require_joysafeter_write
from app.joysafeter_shared.database import get_db
from app.joysafeter_api.services import SecretService

router = APIRouter(tags=["joysafeter-quickstart"])


class QuickstartMessage(BaseModel):
    role: str
    content: str


class QuickstartChatRequest(BaseModel):
    messages: list[QuickstartMessage]
    current_step: int = 1
    secret_ref: str = ""
    agent_context: Optional[dict] = None


def _build_system_prompt(step: int, agent_context: Optional[dict] = None) -> str:
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
        pretty = json.dumps(agent_context, indent=2, ensure_ascii=False)
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
        return [{
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
        }]
    elif step == 3:
        return [{
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
        }]
    elif step == 4:
        return [{
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
        }]
    return []


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
        return json.loads(input_str)
    except json.JSONDecodeError:
        pass

    trimmed = input_str.strip()
    if not trimmed or not trimmed.startswith("{"):
        return None

    patched = list(input_str)
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
        return json.loads(result)
    except json.JSONDecodeError:
        return None


@router.post("/chat")
async def quickstart_chat(
    req: QuickstartChatRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    svc = SecretService(db)
    secrets, _ = await svc.list_secrets(100, None, project_id=auth_ctx.project_id)
    secret = next((s for s in secrets if s.name == req.secret_ref), None)
    if not secret:
        raise HTTPException(404, f"Secret '{req.secret_ref}' not found")

    data = secret.data or {}
    api_key = data.get("ANTHROPIC_AUTH_TOKEN") or data.get("ANTHROPIC_API_KEY") or ""
    base_url = data.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"

    if not api_key:
        raise HTTPException(400, "No ANTHROPIC_API_KEY found in secret")

    system_prompt = _build_system_prompt(req.current_step, req.agent_context)
    tools = _build_tools(req.current_step)

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

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

    async def event_generator():
        tool_name = ""
        tool_json = ""
        in_tool_use = False
        current_step = req.current_step

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{base_url}/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                        "accept": "text/event-stream",
                    },
                    json=claude_body,
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        error_msg = body.decode(errors="replace")
                        event = json.dumps({"type": "error", "message": f"Claude API error: {response.status_code} - {error_msg}"})
                        yield f"data: {event}\n\n"
                        return

                    buffer = ""
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line or line.startswith(":"):
                                continue
                            if line.startswith("data: "):
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
                                        event = json.dumps({"type": "text_delta", "text": text})
                                        yield f"data: {event}\n\n"

                                    elif delta_type == "input_json_delta":
                                        partial = delta.get("partial_json", "")
                                        tool_json += partial
                                        config = _try_parse_partial_json(tool_json)
                                        if config:
                                            event = json.dumps({"type": "config_update", "step": current_step, "config": config})
                                            yield f"data: {event}\n\n"

                                elif evt_type == "content_block_stop":
                                    if in_tool_use:
                                        try:
                                            config = json.loads(tool_json)
                                        except json.JSONDecodeError:
                                            config = {}
                                        event = json.dumps({"type": "config_update", "step": current_step, "config": config})
                                        yield f"data: {event}\n\n"

                                        curl = _generate_curl(tool_name, config)
                                        event = json.dumps({"type": "step_complete", "step": current_step, "resource_id": None, "curl": curl})
                                        yield f"data: {event}\n\n"
                                        in_tool_use = False

                                elif evt_type == "error":
                                    error = evt.get("error", {})
                                    msg = error.get("message", "Unknown error")
                                    event = json.dumps({"type": "error", "message": msg})
                                    yield f"data: {event}\n\n"

            except httpx.HTTPError as e:
                event = json.dumps({"type": "error", "message": str(e)})
                yield f"data: {event}\n\n"

        event = json.dumps({"type": "done"})
        yield f"data: {event}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
