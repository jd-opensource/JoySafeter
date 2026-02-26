"""Background runner for Security Dept tasks."""

from __future__ import annotations

import asyncio
import traceback
import uuid
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.core.database import AsyncSessionLocal
from app.core.redis import RedisClient
from app.core.settings import settings
from app.one_person_security_dept.claude_agent_sdk_python import load_claude_agent_sdk
from app.one_person_security_dept.repositories.task_repository import SecurityDeptTaskRepository
from app.one_person_security_dept.services.event_bus import SecurityDeptEventBus
from app.one_person_security_dept.services.policy_service import SecurityDeptProfile
from app.one_person_security_dept.services.runtime_registry import security_dept_runtime_registry
from app.one_person_security_dept.services.skills_service import SecurityDeptSkillsService

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
_INSTRUCTION_REDIS_KEY = "security_dept:task:{task_id}:instruction"


def _build_system_prompt(profile: SecurityDeptProfile, selected_skills: list[str]) -> str:
    skill_text = ", ".join(selected_skills) if selected_skills else "None"
    return (
        "You are the execution engine of 'One Person Security Dept'. "
        "Operate as a practical penetration testing specialist. "
        f"Profile: {profile.name}. Scenario: {profile.scenario}. "
        "Use tools decisively and provide concrete findings, evidence, and actionable remediation. "
        "When relevant, call out assumptions and confidence. "
        f"Selected skills: {skill_text}."
    )


def _build_user_prompt(*, target: Optional[str], instruction: str, workdir: Path, selected_skills: list[str]) -> str:
    lines = [
        "Run a penetration testing task and report findings.",
        f"Working directory: {workdir}",
        f"Target: {target or 'Not specified'}",
        f"Instruction: {instruction}",
    ]
    if selected_skills:
        lines.append(f"Prefer using these skills when useful: {', '.join(selected_skills)}")
    lines.append("Return concise findings first, then supporting details.")
    return "\n".join(lines)


def _summarize_output(text_parts: list[str], tool_calls: int, tool_results: int) -> str:
    merged = "\n".join(part.strip() for part in text_parts if part and part.strip())
    if not merged:
        return "Task finished. No assistant text summary was produced."

    max_len = 3000
    clipped = merged[:max_len]
    suffix = "" if len(merged) <= max_len else "\n...[truncated]"

    return (
        "## Execution Summary\n"
        f"- Assistant text chunks: {len(text_parts)}\n"
        f"- Tool calls: {tool_calls}\n"
        f"- Tool results: {tool_results}\n\n"
        "## Key Output\n"
        f"{clipped}{suffix}"
    )


async def _mark_failed(task_id: uuid.UUID, error_code: str, error_message: str) -> None:
    async with AsyncSessionLocal() as db:
        repo = SecurityDeptTaskRepository(db)
        task = await repo.get(task_id)
        if task is None or task.status in _TERMINAL_STATUSES:
            return
        task.mark_failed(error_code=error_code, error_message=error_message)
        await db.commit()


async def _mark_cancelled(task_id: uuid.UUID) -> None:
    async with AsyncSessionLocal() as db:
        repo = SecurityDeptTaskRepository(db)
        task = await repo.get(task_id)
        if task is None or task.status in _TERMINAL_STATUSES:
            return
        task.mark_cancelled()
        await db.commit()


async def _mark_completed(
    task_id: uuid.UUID,
    *,
    summary_md: str,
    result_structured: dict[str, Any],
    token_usage: Optional[dict[str, Any]],
    cost_usd: Optional[float],
) -> None:
    async with AsyncSessionLocal() as db:
        repo = SecurityDeptTaskRepository(db)
        task = await repo.get(task_id)
        if task is None or task.status in _TERMINAL_STATUSES:
            return
        task.mark_completed(
            summary_md=summary_md,
            result_structured=result_structured,
            token_usage=token_usage,
            cost_usd=cost_usd,
        )
        await db.commit()


async def _execute_with_sdk(
    *,
    task_id: str,
    profile: SecurityDeptProfile,
    instruction: str,
    target: Optional[str],
    selected_skills: list[str],
) -> tuple[str, dict[str, Any], Optional[dict[str, Any]], Optional[float]]:
    sdk = load_claude_agent_sdk()

    skill_paths = SecurityDeptSkillsService.resolve_skill_paths(selected_skills)

    workdir = Path(settings.security_dept_workdir_root) / task_id
    workdir.mkdir(parents=True, exist_ok=True)

    options = sdk.ClaudeAgentOptions(
        permission_mode=profile.permission_mode,
        cwd=str(workdir),
        add_dirs=skill_paths,
        system_prompt=_build_system_prompt(profile, selected_skills),
        max_turns=20,
        cli_path=settings.security_dept_claude_cli_path,
    )

    prompt = _build_user_prompt(
        target=target,
        instruction=instruction,
        workdir=workdir,
        selected_skills=selected_skills,
    )

    text_parts: list[str] = []
    tool_calls = 0
    tool_results = 0
    token_usage: Optional[dict[str, Any]] = None
    cost_usd: Optional[float] = None

    await SecurityDeptEventBus.publish(task_id, "status", {"message": "Task started", "stage": "running"})

    async for message in sdk.query(prompt=prompt, options=options):
        if isinstance(message, sdk.AssistantMessage):
            for block in message.content:
                if isinstance(block, sdk.TextBlock):
                    content = block.text or ""
                    if content:
                        text_parts.append(content)
                        await SecurityDeptEventBus.publish(task_id, "content", {"delta": content})
                elif isinstance(block, sdk.ToolUseBlock):
                    tool_calls += 1
                    await SecurityDeptEventBus.publish(
                        task_id,
                        "tool_call",
                        {
                            "tool_name": block.name,
                            "tool_input": block.input,
                            "tool_use_id": block.id,
                        },
                    )
                elif isinstance(block, sdk.ToolResultBlock):
                    tool_results += 1
                    await SecurityDeptEventBus.publish(
                        task_id,
                        "tool_result",
                        {
                            "tool_use_id": block.tool_use_id,
                            "is_error": bool(block.is_error),
                            "content": block.content if isinstance(block.content, str) else str(block.content),
                        },
                    )
        elif isinstance(message, sdk.ResultMessage):
            token_usage = message.usage if isinstance(message.usage, dict) else None
            cost_usd = message.total_cost_usd

    summary_md = _summarize_output(text_parts, tool_calls, tool_results)

    result_structured = {
        "workdir": str(workdir),
        "selected_skills": selected_skills,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "assistant_text_preview": "\n".join(text_parts)[:4000],
    }

    return summary_md, result_structured, token_usage, cost_usd


async def run_security_dept_task(
    *,
    task_id: str,
    profile: SecurityDeptProfile,
) -> None:
    """Run one Security Dept task with timeout, cancellation, and status persistence."""

    task_uuid = uuid.UUID(task_id)

    async with security_dept_runtime_registry.semaphore:
        try:
            async with AsyncSessionLocal() as db:
                repo = SecurityDeptTaskRepository(db)
                task_record = await repo.get(task_uuid)
                if task_record is None:
                    return
                if task_record.status in _TERMINAL_STATUSES:
                    return

                task_record.mark_running()
                instruction_preview = task_record.instruction_preview
                target = task_record.target
                selected_skills = list(task_record.selected_skills or [])
                await db.commit()

            await SecurityDeptEventBus.publish(task_id, "status", {"message": "Queued task is now running"})

            execution_instruction = instruction_preview
            if RedisClient.is_available():
                redis_instruction = await RedisClient.get(_INSTRUCTION_REDIS_KEY.format(task_id=task_id))
                if redis_instruction:
                    execution_instruction = redis_instruction

            summary_md, result_structured, token_usage, cost_usd = await asyncio.wait_for(
                _execute_with_sdk(
                    task_id=task_id,
                    profile=profile,
                    instruction=execution_instruction,
                    target=target,
                    selected_skills=selected_skills,
                ),
                timeout=settings.security_dept_task_timeout_seconds,
            )

            await _mark_completed(
                task_uuid,
                summary_md=summary_md,
                result_structured=result_structured,
                token_usage=token_usage,
                cost_usd=cost_usd,
            )
            await SecurityDeptEventBus.publish(task_id, "summary", {"summary_md": summary_md})
            await SecurityDeptEventBus.publish(task_id, "done", {"status": "completed"})

        except asyncio.CancelledError:
            await _mark_cancelled(task_uuid)
            await SecurityDeptEventBus.publish(task_id, "done", {"status": "cancelled"})
            raise
        except asyncio.TimeoutError:
            message = f"Task exceeded timeout of {settings.security_dept_task_timeout_seconds} seconds"
            await _mark_failed(task_uuid, "TIMEOUT", message)
            await SecurityDeptEventBus.publish(task_id, "error", {"code": "TIMEOUT", "message": message})
            await SecurityDeptEventBus.publish(task_id, "done", {"status": "failed"})
        except ImportError as exc:
            message = f"claude-agent-sdk is not installed: {exc}"
            await _mark_failed(task_uuid, "SDK_IMPORT_ERROR", message)
            await SecurityDeptEventBus.publish(task_id, "error", {"code": "SDK_IMPORT_ERROR", "message": message})
            await SecurityDeptEventBus.publish(task_id, "done", {"status": "failed"})
        except Exception as exc:
            logger.error(f"SecurityDept task failed: task={task_id} error={exc}\n{traceback.format_exc()}")
            message = str(exc)
            await _mark_failed(task_uuid, type(exc).__name__, message)
            await SecurityDeptEventBus.publish(
                task_id,
                "error",
                {"code": type(exc).__name__, "message": message},
            )
            await SecurityDeptEventBus.publish(task_id, "done", {"status": "failed"})
        finally:
            if RedisClient.is_available():
                try:
                    await RedisClient.delete(_INSTRUCTION_REDIS_KEY.format(task_id=task_id))
                except Exception:
                    pass
