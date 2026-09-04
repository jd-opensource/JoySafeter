"""Quickstart design-phase orchestration.

This application service owns the model prompt, tool contract, and translation
from provider-neutral model events into the canonical Quickstart design events.
Transport adapters only encode these events for their protocol.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any, Optional, cast

from pydantic import TypeAdapter

from app.joysafeter_domain.agents.configuration_policy import AgentConfigurationPolicy
from app.joysafeter_domain.quickstart import QuickstartArtifact, QuickstartPhase
from app.joysafeter_domain.schemas.joysafeter_agent import McpServerConfig
from app.joysafeter_domain.schemas.joysafeter_quickstart import QuickstartAgentContext
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure
from app.joysafeter_shared.common.stream_errors import async_error_payload
from app.joysafeter_shared.json_boundary import normalize_json_value

logger = logging.getLogger(__name__)

_MCP_SERVER_LIST_ADAPTER = TypeAdapter(list[McpServerConfig])


def _canonical_mcp_server_list_schema() -> tuple[dict[str, Any], dict[str, Any]]:
    schema = _MCP_SERVER_LIST_ADAPTER.json_schema()
    definitions = cast(dict[str, Any], schema.pop("$defs", {}))
    return schema, definitions


class QuickstartDesignService:
    """Own the complete design-generation contract and event state machine."""

    def build_system_prompt(
        self,
        *,
        agent_context: Optional[dict[str, Any]] = None,
        available_skills: Optional[list[dict[str, Any]]] = None,
    ) -> str:
        agent_section = ""
        if agent_context:
            pretty = json.dumps(agent_context, indent=2, ensure_ascii=False)
            agent_section = (
                "\n\n## Existing Agent Draft\n"
                f"```json\n{pretty}\n```\n"
                "Refine this draft while preserving user-confirmed decisions."
            )

        skill_catalog = normalize_json_value(available_skills or [])
        skill_section = (
            "\n\n## Available Skills\n"
            "Only attach Skill IDs from this catalog. If no listed Skill is genuinely useful, return an empty skills array. "
            "Never invent a Skill ID.\n"
            f"```json\n{json.dumps(skill_catalog, indent=2, ensure_ascii=False)}\n```"
        )

        return f"""You are an elite AI agent architect specializing in crafting high-performance agent configurations for the JoySafeter platform. Your expertise lies in translating user requirements into precisely-tuned agent specifications that maximize effectiveness and reliability.

IMPORTANT: Communicate in the same language as the user. If the user writes in Chinese, respond in Chinese.

Current phase: Design — produce one professional Agent blueprint.{agent_section}{skill_section}

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
- mcp_servers: include only MCP services the Agent itself must connect to, using the canonical Agent transports `streamable_http`, `sse`, or `local_stdio`; remote entries must include `url` and `auth_requirement`
- metadata: language, schedule, topic etc.
- blueprint: the complete professional Agent Blueprint described above

Rules:
- Be concise. No lengthy explanations.
- Use tools when you have sufficient information. Prefer making a recommendation immediately only when the user's requirements are sufficient; otherwise ask ONE focused clarifying question.
- After using a tool, briefly explain what was configured."""

    def build_tools(self) -> list[dict[str, Any]]:
        mcp_servers_schema, mcp_server_definitions = _canonical_mcp_server_list_schema()
        return [
            {
                "name": "generate_agent_config",
                "description": "Generate agent configuration based on user requirements",
                "input_schema": {
                    "$defs": mcp_server_definitions,
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
                        "mcp_servers": mcp_servers_schema,
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

    async def stream_events(
        self,
        events: AsyncIterator[dict[str, Any]],
    ) -> AsyncIterator[dict[str, Any]]:
        completed_tool = False
        tool_args: dict[str, str] = {}
        async for event in events:
            event_type = event.get("type")
            if event_type == "text_delta":
                yield event
            elif event_type == "tool_call_delta":
                key = str(event.get("id") or "0")
                tool_args[key] = tool_args.get(key, "") + str(event.get("args") or "")
                config = self._try_parse_partial_json(tool_args[key])
                if config:
                    yield self._config_event(config)
            elif event_type == "tool_call_complete" and not completed_tool:
                key = str(event.get("id") or "0")
                args_json = str(event.get("args_json") or tool_args.get(key, ""))
                try:
                    config = json.loads(args_json)
                except json.JSONDecodeError as exc:
                    log_boundary_failure(
                        logger,
                        boundary="quickstart_application",
                        code="QUICKSTART_TOOL_OUTPUT_INVALID",
                        message="Quickstart model returned invalid tool arguments",
                        operation="parse_tool_arguments",
                        error=exc,
                        data={"phase": QuickstartPhase.DESIGN, "raw_length": len(args_json)},
                        source="upstream",
                        retryable=True,
                        user_action="retry",
                    )
                    yield self._invalid_tool_output_event(
                        message="Model returned an invalid configuration. Please retry."
                    )
                    return
                if not isinstance(config, dict) or not config:
                    yield self._invalid_tool_output_event(
                        message="Model returned an empty configuration. Please retry."
                    )
                    return
                try:
                    validated_context = QuickstartAgentContext.model_validate(config)
                    validated_config = validated_context.model_dump(mode="json", exclude_none=True)
                    mcp_servers = [server.to_persisted() for server in validated_context.mcp_servers or []]
                    AgentConfigurationPolicy.validate_mcp_servers(
                        mcp_servers,
                        require_https=False,
                    )
                    AgentConfigurationPolicy.validate_tool_mcp_references(
                        validated_context.tools,
                        mcp_servers,
                    )
                except (ValueError, AppError) as exc:
                    log_boundary_failure(
                        logger,
                        boundary="quickstart_application",
                        code="QUICKSTART_TOOL_OUTPUT_INVALID",
                        message="Quickstart model returned an invalid Agent draft",
                        operation="validate_tool_arguments",
                        error=exc,
                        data={"phase": QuickstartPhase.DESIGN},
                        source="upstream",
                        retryable=True,
                        user_action="retry",
                    )
                    yield self._invalid_tool_output_event(
                        message="Model returned an invalid configuration. Please retry."
                    )
                    return
                completed_tool = True
                yield self._config_event(validated_config)
                yield {
                    "type": "phase_complete",
                    "phase": QuickstartPhase.DESIGN,
                    "artifact": QuickstartArtifact.AGENT_BLUEPRINT,
                }
            elif event_type == "error":
                yield event
                return
            elif event_type == "done":
                break

        if not completed_tool:
            yield self._invalid_tool_output_event(
                message="Model stopped before returning a complete configuration. Please retry."
            )
            return
        yield {"type": "done"}

    @staticmethod
    def _config_event(config: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "config_update",
            "phase": QuickstartPhase.DESIGN,
            "artifact": QuickstartArtifact.AGENT_BLUEPRINT,
            "config": config,
        }

    @staticmethod
    def _invalid_tool_output_event(*, message: str) -> dict[str, Any]:
        return async_error_payload(
            code="UPSTREAM_INVALID_RESPONSE",
            message=message,
            data={"phase": QuickstartPhase.DESIGN},
            source="upstream",
            retryable=True,
            user_action="retry",
        )

    @staticmethod
    def _try_parse_partial_json(input_str: str) -> Optional[dict[str, Any]]:
        input_str = input_str.strip()
        if not input_str.startswith("{"):
            return None

        in_string = False
        escape_next = False
        stack: list[str] = []

        for character in input_str:
            if escape_next:
                escape_next = False
                continue
            if character == "\\" and in_string:
                escape_next = True
                continue
            if character == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if character == "{":
                stack.append("}")
            elif character == "[":
                stack.append("]")
            elif character in ("}", "]") and stack:
                stack.pop()

        result = input_str
        if in_string:
            result += '"'
        trimmed_end = result.rstrip()
        if trimmed_end.endswith(","):
            result = trimmed_end[:-1]
        result += "".join(reversed(stack))

        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return None
        return cast(Optional[dict[str, Any]], parsed) if isinstance(parsed, dict) else None
