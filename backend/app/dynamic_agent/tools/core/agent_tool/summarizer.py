# agent/tools/core/agent_tool/summarizer.py
# Summary generation and plan update helpers

from typing import Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from loguru import logger

from app.dynamic_agent.models.execution_plan import ExecutionPlan, PlanStep
from app.dynamic_agent.models.subagent_summary import SubagentSummary, create_summary_from_result


def _stream_plan_update(plan: ExecutionPlan, metadata: dict) -> None:
    """
    Stream plan update to response queue if available.

    Args:
        plan: The ExecutionPlan to output
        metadata: Metadata context containing response_queue
    """
    response_queue = metadata.get("response_queue")
    if response_queue and plan:
        try:
            plan_md = plan.to_markdown()
            response_queue.put_nowait(
                {
                    "type": "plan_update",
                    "content": plan_md,
                }
            )
            logger.debug(f"📋 Plan update streamed: {plan.get_progress_summary()}")
        except Exception as e:
            logger.warning(f"Failed to stream plan update: {e}")


async def _generate_alternative_steps(
    error: str,
    context: str,
    llm_instance: BaseChatModel,
) -> list:
    """
    Generate alternative steps when retry exhausted.

    Args:
        error: The error that caused failure
        context: Task context
        llm_instance: LLM for generating alternatives

    Returns:
        List of PlanStep objects for alternative approach
    """
    prompt = f"""The following task failed after multiple retries:

Context: {context[:500]}
Error: {error}

Suggest 2-3 alternative steps to achieve the same goal using a different approach.
Format each step as a single line description.
Be specific and actionable."""

    try:
        response = await llm_instance.ainvoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        content_str = str(content) if content is not None else ""
        lines = content_str.strip().split("\n")
        steps = [
            PlanStep(step_id=str(i + 1), description=line.strip().lstrip("0123456789.-) "))
            for i, line in enumerate(lines)
            if line.strip() and len(line.strip()) > 5
        ][:3]  # Max 3 alternative steps
        return steps
    except Exception as e:
        logger.error(f"Failed to generate alternative steps: {e}")
        return [PlanStep(step_id="1", description="Retry with manual intervention")]


async def _generate_summary(
    result: str,
    task_detail: str,
    success: bool,
    error: Optional[str],
    duration_ms: int,
    llm_instance: BaseChatModel,
) -> SubagentSummary:
    """
    Generate a structured summary from subagent execution result.

    Uses LLM to extract key information and format as SubagentSummary.
    Falls back to text extraction if LLM fails.

    Args:
        result: Raw execution result
        task_detail: Original task description
        success: Whether execution succeeded
        error: Error message if failed
        duration_ms: Execution duration
        llm_instance: LLM for summary generation

    Returns:
        SubagentSummary instance
    """
    # First try simple extraction (faster, no LLM call)
    summary = create_summary_from_result(result, success, error, duration_ms)

    # If we have good coverage, skip LLM call
    # Also skip if result is already XML format (Sub-Agent output)
    if summary.get_coverage_score() > 0.3 or len(result) < 200 or "<result>" in result:
        return summary

    # Use LLM for better extraction on complex results (rare case)
    try:
        prompt = f"""Summarize this execution result as XML:

Task: {task_detail}

Result:
{result}

Return XML format:
<result>
  <success>true|false</success>
  <discovery_type>credentials|endpoint|vulnerability|flag|none</discovery_type>
  <key_findings>
    <finding>key discovery 1</finding>
  </key_findings>
  <extracted_values>
    <cookie>if found</cookie>
    <credentials>if found</credentials>
    <endpoint>if found</endpoint>
    <flag>if found</flag>
  </extracted_values>
</result>

Rules:
- MAX 300 chars total
- NO suggestions or next steps
- Preserve cookies, IDs, flags exactly"""

        response = await llm_instance.ainvoke([HumanMessage(content=prompt)])
        # Extract content as string - response.content may be str or list
        content_str = response.content if isinstance(response.content, str) else str(response.content)
        llm_summary = SubagentSummary.from_llm_response(content_str, duration_ms)

        # Merge with simple extraction to ensure nothing is lost
        if llm_summary.extracted_values:
            summary.extracted_values.update(llm_summary.extracted_values)
        if llm_summary.key_findings:
            # Add unique findings
            existing = set(summary.key_findings)
            for finding in llm_summary.key_findings:
                if finding not in existing:
                    summary.key_findings.append(finding)
        if llm_summary.next_hint and not summary.next_hint:
            summary.next_hint = llm_summary.next_hint

        return summary
    except Exception as e:
        logger.warning(f"LLM summary generation failed: {e}, using simple extraction")
        return summary


async def _consolidate_results(
    raw_results: str,
    task_count: int,
    success_count: int,
    llm_instance: BaseChatModel,
) -> str:
    """
    Use LLM to consolidate multiple Sub-Agent task results into a single summary.

    Args:
        raw_results: Combined raw results from all tasks
        task_count: Total number of tasks
        success_count: Number of successful tasks
        llm_instance: LLM for consolidation

    Returns:
        Consolidated summary string
    """
    prompt = f"""Consolidate these {task_count} task results into ONE concise summary.

{raw_results}

Rules:
1. MERGE duplicates - same endpoint/vulnerability = ONE entry
2. PRESERVE all: endpoints, credentials, cookies, flags, status codes
3. REMOVE: verbose descriptions, repeated info, suggestions
4. NO "Next step" - Main Agent decides that
5. MAX 400 chars

Output format:
**Findings** ({success_count}/{task_count} ok):
- [finding 1]
- [finding 2]

**Extracted**: endpoint=/path, cookie=xxx"""

    response = await llm_instance.ainvoke([HumanMessage(content=prompt)])
    content = response.content if hasattr(response, "content") else str(response)
    if isinstance(content, list):
        content = " ".join(str(item) for item in content)
    content_str = str(content) if content is not None else ""
    return content_str.strip()


def _request_user_guidance(plan: ExecutionPlan, error: str) -> str:
    """
    Generate a message requesting user guidance after replan failure.

    Args:
        plan: The failed execution plan
        error: The final error

    Returns:
        Formatted message for user
    """
    completed = [s for s in plan.steps if s.status == "completed"]
    failed = [s for s in plan.steps if s.status == "failed"]

    msg_lines = [
        "## ⚠️ User Guidance Required",
        "",
        "Task failed after retries and replan attempts.",
        "",
        f"**Completed Steps**: {len(completed)}",
        f"**Failed Steps**: {len(failed)}",
        "",
        f"**Final Error**: {error[:200]}",
        "",
        "Please provide one of the following:",
        "1. Alternative approach or command",
        "2. Additional context information",
        "3. Confirmation to skip this step",
    ]

    if plan.replan_history:
        msg_lines.extend(
            [
                "",
                "**Replan History**:",
            ]
        )
        for rp in plan.replan_history:
            msg_lines.append(f"- {rp['reason']}")

    return "\n".join(msg_lines)
