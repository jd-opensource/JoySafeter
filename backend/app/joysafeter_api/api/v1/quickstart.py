"""Quickstart chat endpoint — streams provider responses via SSE.

Translates user intent into agent/environment/MCP credential group configurations using
tool calls, streaming text deltas and config updates back to the frontend.
"""

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal, Optional, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_api.api.v1.audit import credential_audit_actor
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import CredentialAccessContext
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
from app.joysafeter_shared.json_boundary import normalize_json_value
from app.joysafeter_shared.llm.base_url import LLMBaseUrlError, validate_llm_base_url
from app.joysafeter_shared.llm.model_stream import stream_model

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
    metadata: Optional[dict[str, Any]] = None
    blueprint: Optional[dict[str, Any]] = None


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
        skill_catalog = normalize_json_value([skill.model_dump() for skill in available_skills or []])
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
- a structured capability plan separating Skills, built-in tools, and MCP servers, including why and when each capability is used
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
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "purpose": {"type": "string"},
                                                    "when_used": {"type": "string"},
                                                    "skill_id": {"type": "string"},
                                                },
                                                "required": ["name", "purpose", "when_used"],
                                            },
                                        },
                                        "tools": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "purpose": {"type": "string"},
                                                    "when_used": {"type": "string"},
                                                },
                                                "required": ["name", "purpose", "when_used"],
                                            },
                                        },
                                        "mcp_servers": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "purpose": {"type": "string"},
                                                    "when_used": {"type": "string"},
                                                    "server_url": {"type": "string"},
                                                },
                                                "required": ["name", "purpose", "when_used"],
                                            },
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
                        "description": {
                            "type": "string",
                            "description": "What MCP server credentials this group authorizes",
                        },
                        "mcp_server_url": {
                            "type": "string",
                            "description": "First MCP server URL to authorize when known",
                        },
                        "credential_name": {
                            "type": "string",
                            "description": "Optional name for the first MCP credential member",
                        },
                    },
                    "required": ["name"],
                },
            }
        ]
    return []


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


def _invalid_tool_output_event(*, step: int, message: str) -> dict[str, Any]:
    return async_error_payload(
        code="UPSTREAM_INVALID_RESPONSE",
        message=message,
        data={"step": step},
        source="upstream",
        retryable=True,
        user_action="retry",
    )


async def _stream_quickstart_events(
    events: AsyncIterator[dict[str, Any]],
    *,
    current_step: int,
    requires_tool: bool,
) -> AsyncIterator[str]:
    completed_tool = False
    tool_args: dict[str, str] = {}
    async for event in events:
        event_type = event.get("type")
        if event_type == "text_delta":
            yield _sse_event(event)
        elif event_type == "tool_call_delta":
            key = str(event.get("id") or "0")
            tool_args[key] = tool_args.get(key, "") + str(event.get("args") or "")
            config = _try_parse_partial_json(tool_args[key])
            if config:
                yield _sse_event({"type": "config_update", "step": current_step, "config": config})
        elif event_type == "tool_call_complete" and not completed_tool:
            key = str(event.get("id") or "0")
            args_json = str(event.get("args_json") or tool_args.get(key, ""))
            try:
                config = json.loads(args_json)
            except json.JSONDecodeError as exc:
                log_boundary_failure(
                    logger,
                    boundary="quickstart_api",
                    code="QUICKSTART_TOOL_OUTPUT_INVALID",
                    message="Quickstart model returned invalid tool arguments",
                    operation="parse_tool_arguments",
                    error=exc,
                    data={"step": current_step, "raw_length": len(args_json)},
                    source="upstream",
                    retryable=True,
                    user_action="retry",
                )
                yield _sse_event(
                    _invalid_tool_output_event(
                        step=current_step,
                        message="Model returned an invalid configuration. Please retry.",
                    )
                )
                return
            if not isinstance(config, dict) or not config:
                yield _sse_event(
                    _invalid_tool_output_event(
                        step=current_step,
                        message="Model returned an empty configuration. Please retry.",
                    )
                )
                return
            completed_tool = True
            yield _sse_event({"type": "config_update", "step": current_step, "config": config})
            yield _sse_event(
                {
                    "type": "step_complete",
                    "step": current_step,
                    "resource_id": None,
                    "curl": _generate_curl(str(event.get("name") or ""), config),
                }
            )
        elif event_type == "error":
            yield _sse_event(event)
            return
        elif event_type == "done":
            break

    if requires_tool and not completed_tool:
        yield _sse_event(
            _invalid_tool_output_event(
                step=current_step,
                message="Model stopped before returning a complete configuration. Please retry.",
            )
        )
        return
    yield _sse_event({"type": "done"})


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


@router.post("/chat")
async def quickstart_chat(
    req: QuickstartChatRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
):
    actor = credential_audit_actor(request, auth_ctx)
    application = compose_credential_application(
        db,
        auto_commit=False,
        audit_actor=actor,
    )
    try:
        binding = build_model_inference_policy(
            get_llm_catalog(),
            project_id=auth_ctx.project_id,
            credential_id=req.model_credential_id,
            engine_kind=req.engine_kind,
            model_id=req.agent_context.model if req.agent_context is not None else None,
        )
        material, resolution = await application.material_access_service.resolve_model_inference(
            binding,
            context=CredentialAccessContext(
                consumer_type="quickstart_chat",
                consumer_id="quickstart",
                actor=actor,
            ),
        )
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
    if not model:
        raise InvalidRequestError(
            code="QUICKSTART_MODEL_REQUIRED",
            message=f"{resolution.model_key or 'model'} is required for this provider",
            data={"provider": provider, "protocol": protocol, "key": resolution.model_key},
            user_action="fix_input",
        )

    system_prompt = _build_system_prompt(
        req.current_step,
        req.agent_context,
        req.available_skills,
    )
    tools = _build_tools(req.current_step)

    messages = [{"role": m.role, "content": m.content} for m in req.messages]

    if protocol == "anthropic_messages":
        auth_token = data.get("ANTHROPIC_AUTH_TOKEN") or ""
        api_key = auth_token or data.get("ANTHROPIC_API_KEY") or ""
        bearer_token = bool(auth_token)
    elif protocol in {"openai_responses", "chat_completions"}:
        api_key = data.get("OPENAI_API_KEY") or ""
        bearer_token = False
    else:
        raise InvalidRequestError(
            code="QUICKSTART_PROTOCOL_UNSUPPORTED",
            message=f"Quickstart does not support protocol '{protocol}'",
            data={"provider": provider, "protocol": protocol},
            user_action="fix_input",
        )

    async def event_generator():
        events = stream_model(
            protocol=protocol,
            base_url=base_url,
            api_key=api_key,
            bearer_token=bearer_token,
            model=model,
            system=system_prompt,
            messages=messages,
            tools=tools,
            force_tool_name=(str(tools[0]["name"]) if tools and req.current_step in (2, 3, 4) else None),
            max_tokens=4096,
        )
        async for event in _stream_quickstart_events(
            events,
            current_step=req.current_step,
            requires_tool=bool(tools),
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
