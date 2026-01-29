import asyncio
import os
import time
from typing import List

from langchain_core.tools import tool

from app.dynamic_agent.core.shared_constants import AGENT_TOOL
from app.dynamic_agent.infra.llm import create_llm_instance
from app.dynamic_agent.infra.metadata_context import MetadataContext
from app.dynamic_agent.models.extracted_state import extract_key_state

from .agent_tool_prompts import AGENT_TOOL_DESCRIPTION
from .models import AgentResult
from .retry_handler import _process_one_with_retry

try:
    from app.dynamic_agent.infra.todo_display import get_todo_display
except ImportError:
    get_todo_display = None  # type: ignore[assignment]

try:
    from app.dynamic_agent.models.session_context import SessionContext as AgentSessionContext
except ImportError:
    AgentSessionContext = None  # type: ignore[assignment, misc]

# Configuration constants
MAX_AGENT_LEVEL = int(os.environ.get("MAX_AGENT_LEVEL", 3))
MAX_CONCURRENT_AGENTS = int(os.environ.get("MAX_CONCURRENT_AGENTS", 10))
DEFAULT_TIMEOUT_SECONDS = 2 * 3600
MAX_GOAL_LENGTH = 10000

from loguru import logger  # noqa: E402


@tool(AGENT_TOOL, description=AGENT_TOOL_DESCRIPTION)
async def agent_tool(context: str, task_details: List[str], level: int) -> str:
    """Delegate tasks to Sub-Agent for autonomous execution.

    Args:
        context: Background info - what you discovered, why you suspect this attack vector
        task_details: task details
        level: agent level
    """
    # Validate input
    if not task_details:
        return "agent_tool requires at least one task"

    if level > MAX_CONCURRENT_AGENTS:
        logger.warning(
            f"Requested {len(task_details)} agents exceeds max {MAX_CONCURRENT_AGENTS}, will process in batches"
        )
        return (
            f"Requested {len(task_details)} agents exceeds max {MAX_CONCURRENT_AGENTS}, "
            f"you need to reduce and retain the high priority agents"
        )

    task_details_enhanced = [f"\ncontext:\n{context}\n\ntask_detail:\n{detail}" for detail in task_details]

    # Initialize state with target URL extracted from context
    accumulated_state = extract_key_state(context)
    if accumulated_state.target_url:
        logger.info(f"🎯 Target URL extracted: {accumulated_state.target_url}")

    # Generate unique context ID for this SubAgent to isolate used tricks
    # New SubAgents don't share context with previous ones, so they shouldn't
    # inherit the "used tricks" from previous SubAgents
    import uuid

    subagent_context_id = f"subagent_{uuid.uuid4().hex[:8]}_{int(time.time())}"

    # Set context ID and inject available tricks from knowledge base (if any)
    from app.dynamic_agent.tools.builtin.knowledge_search_tool import format_tricks_for_planning, set_context_id

    set_context_id(subagent_context_id)
    tricks_hint = format_tricks_for_planning()

    # Inject all findings from report_finding into sub-agent context
    # This ensures sub-agent has access to cookies, credentials, endpoints discovered during recon
    from app.dynamic_agent.tools.builtin.report_finding_tool import get_findings_store

    findings = get_findings_store()
    findings_context = ""
    if findings:
        findings_lines = [f"  - {k}: {v}" for k, v in findings.items()]
        findings_context = "\n\n**Recon Findings (use these in your requests):**\n" + "\n".join(findings_lines)
        logger.info(f"📋 Injecting {len(findings)} findings into sub-agent context: {list(findings.keys())}")

    task_details_enhanced = []
    for task in task_details:
        one_task_enhanced = f"\ncontext:\n{context}{findings_context}\n\ntask_detail:\n{task}"
        if tricks_hint:
            one_task_enhanced += f"\n{tricks_hint}"
        task_details_enhanced.append(one_task_enhanced)

    async def _run_all() -> List[AgentResult]:
        """Run all agents concurrently with timeout."""
        # Create tasks for concurrent execution
        tasks = [
            _process_one_with_retry(
                task_detail,
                level,
                create_llm_instance(),
                max_retries=3,
                accumulated_state=accumulated_state if not accumulated_state.is_empty() else None,
            )
            for task_detail in task_details_enhanced
        ]

        # Apply timeout to all tasks
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=DEFAULT_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.error(f"Agent execution timed out after {DEFAULT_TIMEOUT_SECONDS}s")
            # Return timeout errors for all tasks
            return [
                AgentResult(name=task_details[idx], level=level, duration_ms=0, ok=False, result="", error="Timeout")
                for idx in range(len(task_details))
            ]

        # Handle exceptions from gather
        processed_results: List[AgentResult] = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Agent {idx} raised exception: {result}")
                processed_results.append(
                    AgentResult(
                        name=task_details[idx], level=level, duration_ms=0, ok=False, result="", error=str(result)
                    )
                )
            elif isinstance(result, AgentResult):
                processed_results.append(result)
            else:
                # Should not happen, but handle gracefully
                logger.warning(f"Unexpected result type: {type(result)}")
                processed_results.append(
                    AgentResult(
                        name=task_details[idx],
                        level=level,
                        duration_ms=0,
                        ok=False,
                        result="",
                        error=f"Unexpected result type: {type(result)}",
                    )
                )

        return processed_results

    # Execute all agents concurrently
    try:
        results = await _run_all()
    except Exception as e:
        error = f"Failed to run all agents: {e}"
        logger.error(error, exc_info=True)
        return error

    success_count = 0
    final_results: List[str] = []
    for idx, r in enumerate(results):
        # logger.info(f"Agent {task_details[idx]} result: {r}")
        if not r:
            temp_result = f"task `{task_details[idx]}` failed"
            logger.warning(temp_result)
            final_results.append(temp_result)
            continue
        if asyncio.iscoroutine(r):
            temp = await r
            if isinstance(temp, AgentResult):
                temp_result = temp.result if temp.result else (temp.error or "")
            else:
                temp_result = str(temp)
            final_results.append(temp_result)
            success_count += 1
        else:
            # temp_result = f"task {task_details[idx]} failed, result is: \n{str(r)}"
            # logger.warning(temp_result)
            # final_results.append(temp_result)r
            if isinstance(r, AgentResult):
                temp_result = r.result if r.result else (r.error or "")
            else:
                temp_result = str(r)
            final_results.append(temp_result)
            success_count += 1

    logger.info(f"agent_tool completed: {success_count}/{len(results)} succeeded")

    if len(task_details) == 1:
        first_result = results[0]
        if isinstance(first_result, AgentResult):
            ret_str = first_result.result if first_result.result else (first_result.error or "")
        else:
            ret_str = str(first_result) if first_result else ""
        metadata = MetadataContext.get() or {}
        if metadata.get("flag_found"):
            flag_value = metadata.get("found_flag", "FLAG{...}")
            # Return FLAG banner + full Sub-Agent result for accurate attack path
            return f"🏁 FLAG FOUND: {flag_value}\n\n{ret_str}"

    rets: List[str] = []
    for idx, result_str in enumerate(final_results):
        rets.append(f"Task: {task_details[idx]}\nResult:{result_str}\n")

    ret_str = ("-" * 10).join(rets)

    from app.dynamic_agent.tools.builtin.check_iteration_tool.check_iteration_tool import build_iteration_info

    return f"""{ret_str}.

    ------
    extra info about iteration limit:
    {build_iteration_info()}
    ------

    """
