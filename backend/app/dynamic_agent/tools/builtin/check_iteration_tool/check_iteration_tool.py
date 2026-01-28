import os
from uuid import UUID

from langchain_core.tools import tool
from loguru import logger

# Default iteration limit
DEFAULT_ITERATION_LIMIT = int(os.getenv("DEFAULT_ITERATION_LIMIT", "30"))

# Warning thresholds
WARNING_THRESHOLD = 0.75  # 90% of limit
CRITICAL_THRESHOLD = 0.85  # 95% of limit


@tool
def check_iterations() -> str:
    """Check current iteration count and receive guidance on next steps.

    Use this tool to:
    - Track your iteration usage during task execution
    - Know when to wrap up and provide final response
    - Avoid exceeding iteration limits
    - Ensure timely responses to users

    Returns:
        str: Guidance message with current iteration count, remaining iterations, and next steps.

    When to use this tool:
    - At the START of your task - to know your iteration budget
    - After completing major milestones - to assess remaining iterations
    - Before starting complex operations - to ensure you have enough iterations
    - When stuck or making slow progress - to decide whether to wrap up
    - Periodically (every 5-10 tool calls) - to stay aware of your usage

    Iteration limit includes ALL tool invocations: LLM calls, tool executions,
    planning tools, and any other tool usage.
    """
    try:
        return build_iteration_info()
    except Exception as e:
        logger.error(f"Error checking iterations: {e}", exc_info=True)
        return f"Error checking iteration count: {str(e)}"


def build_iteration_info() -> str:
    from app.dynamic_agent.observability.tracking import _get_current_task_id, get_task_iteration_count

    task_id = _get_current_task_id()

    if task_id is None:
        return "No task_id found in context. Cannot check iterations."

    # Convert to UUID if string
    if isinstance(task_id, str):
        try:
            task_id = UUID(task_id)
        except ValueError:
            return f"Invalid task_id format: {task_id}"

    # Get current iteration count
    limit = DEFAULT_ITERATION_LIMIT
    current_iteration = get_task_iteration_count(task_id)
    remaining = limit - current_iteration
    usage_ratio = current_iteration / limit

    # Generate guidance based on iteration usage
    if current_iteration >= limit:
        return f"""⚠️ CRITICAL: Iteration limit exceeded!

Current iteration: {current_iteration}
Limit: {limit}

⛔ STOP IMMEDIATELY and:
1. Use the final_response tool NOW to provide your complete answer
2. Synthesize all findings you have gathered
3. Provide actionable recommendations based on what you've discovered
4. DO NOT execute any other tools

Your user is waiting for a response - provide it NOW rather than risk timeout.

Remember: A good partial answer is better than no answer due to timeout."""

    elif usage_ratio >= CRITICAL_THRESHOLD:
        return f"""⚠️ WARNING: Very close to iteration limit!

Current iteration: {current_iteration}
Remaining: {remaining}
Limit: {limit}

⛔ STOP new tool executions and:
1. Immediately use the final_response tool to provide your answer
2. Synthesize all findings gathered so far
3. Provide recommendations based on available information

You have only {remaining} iterations remaining - use them ONLY if absolutely critical for finalizing your response.
Better to provide a complete answer now than to exhaust iterations without responding."""

    elif usage_ratio >= WARNING_THRESHOLD:
        return f"""⚠️ Approaching iteration limit

Current iteration: {current_iteration}
Remaining: {remaining}
Limit: {limit}

You have used {int(usage_ratio * 100)}% of your iteration budget.

Plan your final steps carefully:
- Focus ONLY on tools critical to answering the user's request
- Skip exploratory tools or optional verification
- Prepare to provide your final response soon
- Consider wrapping up exploration and moving to final synthesis

Recommendation: Complete your current work, then use final_response tool."""

    else:
        return f"""✓ Iteration status: You have sufficient iterations remaining

Current iteration: {current_iteration}
Remaining: {remaining}
Limit: {limit}

Continue with your task, keeping these tips in mind:
- Focus on high-impact actions that directly address the user's request
- Use agent_tool for time-consuming or parallel subtasks
- Check iterations again after completing major milestones
- Plan strategically but don't over-plan - execute and adapt

You're at {int(usage_ratio * 100)}% of your iteration budget - proceed efficiently."""
