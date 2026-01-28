"""Retry Logic with Error Classification and Recovery.

This module orchestrates retry behavior for Sub-Agent tasks:
- Error classification and retry strategy selection
- Retry loop with backoff
- Error reporting and recovery

Dependencies: executor.py, models.py
"""

import asyncio
import re
from typing import List, Optional

from langchain_core.language_models import BaseChatModel

from app.dynamic_agent.infra.metadata_context import MetadataContext
from app.dynamic_agent.models.execution_plan import ExecutionPlan
from app.dynamic_agent.models.extracted_state import ExtractedState
from app.dynamic_agent.models.hint_tracker import HintTracker
from app.dynamic_agent.models.retry_strategy import (
    RETRY_STRATEGIES,
    classify_error,
    generate_error_report,
)
from app.dynamic_agent.models.todo_panel import TodoPanel

try:
    from app.dynamic_agent.infra.todo_display import get_todo_display
except ImportError:
    get_todo_display = None  # type: ignore[assignment]

from loguru import logger

from .executor import _process_one
from .models import AgentResult
from .summarizer import (
    _generate_alternative_steps,
    _request_user_guidance,
    _stream_plan_update,
)


async def _process_one_with_retry(
    task_detail: str,
    level: int,
    llm: BaseChatModel,
    max_retries: int = 3,
    adjust_on_retry: bool = True,
    accumulated_state: Optional[ExtractedState] = None,
) -> AgentResult:
    """
    Process Sub-Agent task with retry mechanism.

    Args:
        task_detail: Task description
        level: agent level
        llm: Language model instance
        max_retries: Maximum retry attempts
        adjust_on_retry: Whether to add adjustment hints on retry
        accumulated_state: State from previous sequential tasks

    Returns:
        AgentResult with execution details
    """
    error_history: List[str] = []
    last_error = ""

    # T006: Get ExecutionPlan from metadata if available
    metadata = MetadataContext.get() or {}
    plan: Optional[ExecutionPlan] = metadata.get("execution_plan")

    # 006 T018: Get TodoPanel from metadata if available
    todo_panel: Optional[TodoPanel] = metadata.get("todo_panel")

    # T016: Get HintTracker from metadata if available
    hint_tracker: Optional[HintTracker] = metadata.get("hint_tracker")

    # T013: Add accumulated state to task context
    if accumulated_state and not accumulated_state.is_empty():
        state_context = accumulated_state.to_context_string()
        task_detail = f"{task_detail}\n\n**Accumulated State from Previous Steps:**\n{state_context}"

    for attempt in range(max_retries + 1):
        # T015: Add adjustment hints to task on retry
        adjusted_task = task_detail
        if attempt > 0 and adjust_on_retry and last_error:
            error_type = classify_error(last_error)
            strategy = RETRY_STRATEGIES[error_type]

            # Build adjustment hints
            adjustment_hints = []
            for adj in strategy.adjustments:
                adjustment_hints.append(f"- Try to {adj.action} {adj.type} '{adj.key}': {adj.reason}")

            if adjustment_hints:
                adjusted_task = f"""{task_detail}

⚠️ RETRY ATTEMPT {attempt}/{max_retries} - Previous error: {last_error}
Error type: {error_type}
Suggested adjustments:
{chr(10).join(adjustment_hints)}

Please try a different approach based on the suggestions above."""
            else:
                adjusted_task = f"""{task_detail}

⚠️ RETRY ATTEMPT {attempt}/{max_retries} - Previous error: {last_error}
Please try a different approach."""

        # Execute the task
        result = await _process_one(adjusted_task, level, llm)

        if result.ok:
            if attempt > 0:
                logger.info(f"✅ Task succeeded on retry attempt {attempt}")

            # T008: Update plan on success
            if plan:
                plan.advance(result.result[:200] if result.result else "Completed")
                _stream_plan_update(plan, metadata)
                logger.debug(f"📋 Plan advanced: {plan.get_progress_summary()}")

            # 006 T018: Update TodoPanel on success
            if todo_panel:
                current_item = todo_panel.get_current_item()
                if current_item:
                    todo_panel.complete(current_item.id)
                    logger.debug(f"✅ TODO item {current_item.id} completed")
                # Start next pending item
                next_item = todo_panel.get_next_pending()
                if next_item:
                    todo_panel.start(next_item.id)

            # 006: Also update global TodoDisplayManager
            if get_todo_display is not None:
                try:
                    display = get_todo_display()
                    display.complete_current_and_start_next()
                except Exception as e:
                    logger.debug(f"TodoDisplay update failed: {e}")

            # T016: Update hint tracker on success (mark current hint as success)
            if hint_tracker:
                next_hint = hint_tracker.get_next_actionable()
                if next_hint:
                    hint_tracker.mark_success(next_hint.hint_id)
                    logger.debug(f"✅ Hint {next_hint.hint_id} marked as success")

            # 007 T013: Update AgentSessionContext Findings from SubagentSummary
            agent_session_context = metadata.get("agent_session_context") if metadata else None
            if agent_session_context:
                try:
                    # Try to parse result as SubagentSummary JSON
                    result_text = result.result if hasattr(result, "result") else str(result)
                    if result_text:
                        # Note: FLAG detection is handled by report_finding tool
                        # No need to duplicate here - Sub-Agent calls report_finding(key="flag", value="...")

                        # Try XML parsing for structured results (preferred format)
                        try:
                            if "<result>" in result_text and "</result>" in result_text:
                                # Extract discovery_type
                                discovery_match = re.search(r"<discovery_type>([^<]+)</discovery_type>", result_text)
                                if discovery_match and discovery_match.group(1) != "none":
                                    discovery_type = discovery_match.group(1).strip()
                                    agent_session_context.add_finding("last_discovery_type", discovery_type)
                                    logger.debug(f"🔍 Discovery type: {discovery_type}")

                                # Extract suggested_next
                                suggested_match = re.search(r"<suggested_next>([^<]+)</suggested_next>", result_text)
                                if suggested_match:
                                    suggested = suggested_match.group(1).strip()
                                    agent_session_context.add_finding("suggested_next", suggested)
                                    logger.debug(f"💡 Suggested next: {suggested}")

                                # Extract extracted_values
                                values_match = re.search(
                                    r"<extracted_values>(.*?)</extracted_values>", result_text, re.DOTALL
                                )
                                if values_match:
                                    values_block = values_match.group(1)
                                    for tag in ["cookie", "flag", "credentials", "endpoint", "token", "session"]:
                                        tag_match = re.search(rf"<{tag}>([^<]+)</{tag}>", values_block)
                                        if tag_match:
                                            value = tag_match.group(1).strip()
                                            agent_session_context.add_finding(tag, value)
                                            logger.debug(f"🔑 Added finding: {tag}={value[:50]}")

                                # Extract key_findings
                                findings = re.findall(r"<finding>([^<]+)</finding>", result_text)
                                for finding in findings[:5]:
                                    if len(finding) <= 100:
                                        agent_session_context.add_finding("discovery", finding.strip())
                                        logger.debug(f"📝 Added key finding: {finding[:50]}")
                        except Exception as xml_err:
                            logger.debug(f"XML parsing failed: {xml_err}")
                except Exception as e:
                    logger.debug(f"Failed to extract findings: {e}")

            return result

        # Task failed - record error and prepare for retry
        last_error = result.error or "Unknown error"
        error_history.append(f"Attempt {attempt + 1}: {last_error}")

        # Check if we should retry
        error_type = classify_error(last_error)
        strategy = RETRY_STRATEGIES[error_type]

        if attempt < max_retries:
            # T014: Calculate delay with exponential backoff
            delay = strategy.get_delay(attempt)
            logger.warning(
                f"Task failed (attempt {attempt + 1}/{max_retries + 1}), "
                f"error type: {error_type}, retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)
        else:
            # T009: Update plan on failure
            if plan:
                plan.fail_current(last_error[:100])
                _stream_plan_update(plan, metadata)
                logger.debug(f"📋 Plan step failed: {plan.get_progress_summary()}")

            # 006 T018: Update TodoPanel on failure
            if todo_panel:
                current_item = todo_panel.get_current_item()
                if current_item:
                    todo_panel.fail(current_item.id, last_error[:50])
                    logger.debug(f"❌ TODO item {current_item.id} failed")

            # T016: Update hint tracker on failure
            if hint_tracker:
                next_hint = hint_tracker.get_next_actionable()
                if next_hint:
                    hint_tracker.mark_failed(next_hint.hint_id, last_error[:50])
                    logger.debug(f"❌ Hint {next_hint.hint_id} marked as failed")

            # T010: Trigger replan if allowed
            if plan and plan.replan_count == 0:
                logger.info(f"🔄 Triggering replan after {attempt + 1} failed attempts...")

                # 007 T024: Update AgentSessionContext with replan reason
                agent_session_context = metadata.get("agent_session_context") if metadata else None
                replan_reason = f"Retry exhausted: {last_error[:50]}"
                if agent_session_context:
                    agent_session_context.set_replan_reason(replan_reason)
                    logger.info("🔄 Session context updated with replan reason")

                try:
                    new_steps = await _generate_alternative_steps(last_error, task_detail, llm)
                    if new_steps:
                        plan.replan(new_steps, replan_reason)
                        plan.replan_count = 1
                        _stream_plan_update(plan, metadata)
                        logger.info(f"📋 Plan replanned with {len(new_steps)} new steps")

                        # 006 T022: Update TodoPanel with replan
                        if todo_panel:
                            new_descriptions = [s.description for s in new_steps]
                            todo_panel.replan(new_descriptions, replan_reason)
                            logger.info(f"📋 TODO panel replanned with {len(new_steps)} new items")

                        # Continue with first new step
                        if new_steps:
                            new_task = new_steps[0].description
                            logger.info(f"▶️ Executing replanned step: {new_task[:50]}...")

                            # 006 T022: Start first replanned item in TodoPanel
                            if todo_panel:
                                next_item = todo_panel.get_next_pending()
                                if next_item:
                                    todo_panel.start(next_item.id)

                            result = await _process_one(new_task, level, llm)
                            if result.ok:
                                plan.advance(result.result[:200] if result.result else "Completed")
                                _stream_plan_update(plan, metadata)

                                # 006 T022: Complete replanned item in TodoPanel
                                if todo_panel:
                                    current_item = todo_panel.get_current_item()
                                    if current_item:
                                        todo_panel.complete(current_item.id)

                                return result
                except Exception as e:
                    logger.error(f"Replan failed: {e}")

            # T012 & 007 T025: Request user guidance if replan already attempted
            # Pause execution and request user to provide new guidance
            if plan and plan.replan_count >= 1:
                guidance_msg = _request_user_guidance(plan, last_error)

                # 007 T025: Update session context to indicate pause
                agent_session_context = metadata.get("agent_session_context") if metadata else None
                if agent_session_context:
                    agent_session_context.set_replan_reason(
                        f"⏸️ PAUSED: Replan failed. Awaiting user guidance. Error: {last_error[:30]}"
                    )
                    logger.warning("⏸️ Execution paused - replan limit reached, requesting user guidance")

                result.error = f"{last_error}\n\n{guidance_msg}"
                return result

            # T015a: Generate detailed error report
            error_report = generate_error_report(
                error_message=last_error,
                attempts=attempt + 1,
                error_history=error_history,
            )
            logger.error(f"Task failed after {attempt + 1} attempts:\n{error_report}")

            # Return result with error report
            result.error = f"{last_error}\n\n{error_report}"
            return result

    return result


__all__ = ["_process_one_with_retry"]
